"""
Folio — Book ingestion pipeline
================================
1. For each of the 50 seed books, fetch metadata from Open Library.
2. Call Claude Haiku to tag each book across 13 psychological needs.
3. Upsert into `books` and `book_need_tags` via the Supabase service role.

Usage:
    pip install -r requirements.txt
    SUPABASE_URL=... SUPABASE_KEY=... ANTHROPIC_API_KEY=... python ingest_books.py

Estimated API cost: < $0.10 total (Claude Haiku, 50 books).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.parse
from typing import Optional

import anthropic
from supabase import create_client

# ---------------------------------------------------------------------------
# Need ID mapping (mirrors schema.sql needs table — never changes)
# ---------------------------------------------------------------------------

NEED_CODE_TO_ID: dict[str, int] = {
    "being_chosen":          1,
    "surviving":             2,
    "procedural_resolution": 3,
    "moral_complexity":      4,
    "power_agency":          5,
    "wound_visible":         6,
    "making_sense_history":  7,
    "self_remade":           8,
    "inside_power":          9,
    "identity_witnessed":    10,
    "world_larger":          11,
    "creative_kinship":      12,
    "anxiety_named":         13,
}

NEED_DESCRIPTIONS: dict[str, str] = {
    "being_chosen":          "Being perfectly chosen / unconditional romantic or familial love",
    "surviving":             "Surviving the unsurvivable / extreme resilience under catastrophe",
    "procedural_resolution": "Procedural resolution / the satisfying unravelling of a mystery or system",
    "moral_complexity":      "Moral complexity held / sitting with ethical ambiguity without easy answers",
    "power_agency":          "Access to power and agency / claiming autonomy in a system that denies it",
    "wound_visible":         "The wound made visible / trauma named, witnessed, and validated",
    "making_sense_history":  "Making sense of history / understanding how we got here",
    "self_remade":           "The self can be remade / transformation and second chances",
    "inside_power":          "Being inside power / access to elite rooms, politics, strategy",
    "identity_witnessed":    "Identity witnessed / being truly seen in one's full, specific identity",
    "world_larger":          "The world is larger / wonder, discovery, the sublime",
    "creative_kinship":      "Creative kinship / the bond between artists, makers, obsessives",
    "anxiety_named":         "Anxiety named and held / contemporary dread articulated and companioned",
}

# ---------------------------------------------------------------------------
# 50 seed books (title, author) — NYT and Goodreads bestsellers
# Chosen to span all 13 psychological needs broadly.
# ---------------------------------------------------------------------------

SEED_BOOKS: list[tuple[str, str]] = [
    # being_chosen
    ("The Notebook", "Nicholas Sparks"),
    ("Twilight", "Stephenie Meyer"),
    ("Outlander", "Diana Gabaldon"),
    ("It Ends with Us", "Colleen Hoover"),
    # surviving
    ("The Hunger Games", "Suzanne Collins"),
    ("The Road", "Cormac McCarthy"),
    ("Wild", "Cheryl Strayed"),
    ("A Little Life", "Hanya Yanagihara"),
    # procedural_resolution
    ("Gone Girl", "Gillian Flynn"),
    ("The Girl with the Dragon Tattoo", "Stieg Larsson"),
    ("Big Little Lies", "Liane Moriarty"),
    ("In the Woods", "Tana French"),
    # moral_complexity
    ("The Kite Runner", "Khaled Hosseini"),
    ("Atonement", "Ian McEwan"),
    ("The Secret History", "Donna Tartt"),
    ("Crime and Punishment", "Fyodor Dostoevsky"),
    # power_agency
    ("The Handmaid's Tale", "Margaret Atwood"),
    ("Little Fires Everywhere", "Celeste Ng"),
    ("Becoming", "Michelle Obama"),
    ("The Power", "Naomi Alderman"),
    # wound_visible
    ("When Breath Becomes Air", "Paul Kalanithi"),
    ("The Year of Magical Thinking", "Joan Didion"),
    ("Educated", "Tara Westover"),
    ("The Body Keeps the Score", "Bessel van der Kolk"),
    # making_sense_history
    ("Sapiens", "Yuval Noah Harari"),
    ("All the Light We Cannot See", "Anthony Doerr"),
    ("The Nightingale", "Kristin Hannah"),
    ("Pachinko", "Min Jin Lee"),
    # self_remade
    ("Eat Pray Love", "Elizabeth Gilbert"),
    ("The Alchemist", "Paulo Coelho"),
    ("Normal People", "Sally Rooney"),
    ("Eleanor Oliphant Is Completely Fine", "Gail Honeyman"),
    # inside_power
    ("The Final Empire", "Brandon Sanderson"),
    ("House of Cards", "Michael Dobbs"),
    ("1984", "George Orwell"),
    ("Succession", "Jesse Armstrong"),
    # identity_witnessed
    ("The Color Purple", "Alice Walker"),
    ("On Earth We're Briefly Gorgeous", "Ocean Vuong"),
    ("Giovanni's Room", "James Baldwin"),
    ("Americanah", "Chimamanda Ngozi Adichie"),
    # world_larger
    ("Life of Pi", "Yann Martel"),
    ("The Hitchhiker's Guide to the Galaxy", "Douglas Adams"),
    ("Project Hail Mary", "Andy Weir"),
    ("The Alchemist", "Paulo Coelho"),
    # creative_kinship
    ("Tomorrow and Tomorrow and Tomorrow", "Gabrielle Zevin"),
    ("Station Eleven", "Emily St. John Mandel"),
    ("The Paris Wife", "Paula McLain"),
    # anxiety_named
    ("The Midnight Library", "Matt Haig"),
    ("Anxious People", "Fredrik Backman"),
    ("Maybe You Should Talk to Someone", "Lori Gottlieb"),
]

# Deduplicate while preserving order
seen: set[tuple[str, str]] = set()
SEED_BOOKS_DEDUPED: list[tuple[str, str]] = []
for entry in SEED_BOOKS:
    if entry not in seen:
        seen.add(entry)
        SEED_BOOKS_DEDUPED.append(entry)


# ---------------------------------------------------------------------------
# Open Library helpers
# ---------------------------------------------------------------------------

def _ol_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Folio/1.0 (book-ingestion)"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def fetch_open_library(title: str, author: str) -> dict:
    """
    Search Open Library and return a dict ready to INSERT into `books`.
    Falls back gracefully if metadata is missing.
    """
    query = urllib.parse.urlencode({"title": title, "author": author, "limit": 1, "fields": "key,title,author_name,isbn,first_sentence,description,cover_i,first_publish_year,ratings_count,ratings_average"})
    data = _ol_get(f"https://openlibrary.org/search.json?{query}")

    docs = data.get("docs", [])
    if not docs:
        return {"title": title, "author": author}

    doc = docs[0]

    # Description: try first_sentence, then description on the work record
    description: Optional[str] = None
    first_sentence = doc.get("first_sentence")
    if isinstance(first_sentence, dict):
        description = first_sentence.get("value")
    elif isinstance(first_sentence, str):
        description = first_sentence

    if not description:
        work_key = doc.get("key")
        if work_key:
            try:
                work = _ol_get(f"https://openlibrary.org{work_key}.json")
                raw_desc = work.get("description")
                if isinstance(raw_desc, dict):
                    description = raw_desc.get("value")
                elif isinstance(raw_desc, str):
                    description = raw_desc
            except Exception:
                pass

    # Cover URL
    cover_url: Optional[str] = None
    cover_i = doc.get("cover_i")
    if cover_i:
        cover_url = f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"

    # ISBN — take first available
    isbn_list = doc.get("isbn", [])
    isbn = isbn_list[0] if isbn_list else None

    # Ratings — Open Library exposes these in search results
    ratings_count = doc.get("ratings_count") or 0
    avg_rating = doc.get("ratings_average")
    if avg_rating is not None:
        avg_rating = round(float(avg_rating), 2)

    authors = doc.get("author_name", [])

    return {
        "title": doc.get("title", title),
        "author": ", ".join(authors) if authors else author,
        "isbn": isbn,
        "description": description,
        "cover_url": cover_url,
        "pub_year": doc.get("first_publish_year"),
        "ratings_count": int(ratings_count),
        "avg_rating": avg_rating,
    }


# ---------------------------------------------------------------------------
# Anthropic tagging
# ---------------------------------------------------------------------------

TAGGING_SYSTEM = """You are a literary psychologist. Given a book's title, author, and description,
you assign weights (0.0–1.0) reflecting how strongly the book serves each of 13 psychological needs.

Rules:
- Most books serve 2–4 needs strongly (≥0.4); the rest should be 0.0–0.2.
- Weights do not need to sum to 1.
- Be specific: a thriller solves puzzles (procedural_resolution) but may not address trauma (wound_visible) unless it explicitly does.
- For wound_visible, also set has_perpetrator: true if the wound was caused by another person (abuse, violence, betrayal), false if circumstantial (illness, accident, loss).

Respond with valid JSON only — no explanation, no markdown fences."""

TAGGING_USER_TEMPLATE = """Book: "{title}" by {author}

Description: {description}

Score this book across these 13 psychological needs (0.0–1.0 each):

{needs_list}

Return JSON in exactly this shape:
{{
  "being_chosen": 0.0,
  "surviving": 0.0,
  "procedural_resolution": 0.0,
  "moral_complexity": 0.0,
  "power_agency": 0.0,
  "wound_visible": 0.0,
  "making_sense_history": 0.0,
  "self_remade": 0.0,
  "inside_power": 0.0,
  "identity_witnessed": 0.0,
  "world_larger": 0.0,
  "creative_kinship": 0.0,
  "anxiety_named": 0.0,
  "has_perpetrator": false
}}"""


def tag_book(client: anthropic.Anthropic, title: str, author: str, description: str) -> dict:
    """
    Call Claude Haiku to score a book across 13 psychological needs.
    Returns dict with need codes as keys and float weights as values,
    plus 'has_perpetrator' bool.
    """
    needs_list = "\n".join(
        f"  {code}: {desc}"
        for code, desc in NEED_DESCRIPTIONS.items()
    )
    prompt = TAGGING_USER_TEMPLATE.format(
        title=title,
        author=author,
        description=description or "(no description available — infer from title and author)",
        needs_list=needs_list,
    )

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=TAGGING_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # Strip markdown fences if the model adds them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Main ingestion loop
# ---------------------------------------------------------------------------

def ingest_all(dry_run: bool = False) -> None:
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    books = SEED_BOOKS_DEDUPED
    print(f"Ingesting {len(books)} books  (dry_run={dry_run})\n")

    for i, (title, author) in enumerate(books, 1):
        print(f"[{i:02d}/{len(books)}] {title} — {author}")

        # 1. Fetch Open Library metadata
        try:
            meta = fetch_open_library(title, author)
        except Exception as e:
            print(f"  ⚠ Open Library fetch failed: {e} — using title/author only")
            meta = {"title": title, "author": author}

        # 2. Tag psychological needs via Claude
        try:
            tags = tag_book(ai, meta["title"], meta.get("author", author), meta.get("description") or "")
        except Exception as e:
            print(f"  ⚠ Tagging failed: {e} — skipping")
            time.sleep(1)
            continue

        has_perpetrator: Optional[bool] = tags.pop("has_perpetrator", None)

        if dry_run:
            print(f"  meta:  {meta}")
            print(f"  tags:  {tags}")
            print(f"  has_perpetrator: {has_perpetrator}")
            continue

        # 3. Upsert book
        book_result = (
            db.table("books")
            .upsert(meta, on_conflict="title,author")
            .execute()
        )
        if not book_result.data:
            print(f"  ⚠ Book upsert returned no data — skipping tags")
            continue

        book_id = book_result.data[0]["id"]
        print(f"  book_id: {book_id}")

        # 4. Insert need tags
        tag_rows = []
        for code, weight in tags.items():
            need_id = NEED_CODE_TO_ID.get(code)
            if need_id is None:
                continue
            w = max(0.0, min(1.0, float(weight)))
            if w == 0.0:
                continue  # skip zero-weight tags
            row = {
                "book_id": book_id,
                "need_id": need_id,
                "weight": round(w, 3),
                "source": "llm",
            }
            if code == "wound_visible" and has_perpetrator is not None:
                row["has_perpetrator"] = has_perpetrator
            tag_rows.append(row)

        if tag_rows:
            db.table("book_need_tags").upsert(tag_rows, on_conflict="book_id,need_id").execute()
            top = sorted(tag_rows, key=lambda r: r["weight"], reverse=True)[:3]
            top_str = ", ".join(f"{NEED_CODE_TO_ID[r['need_id']] if False else list(NEED_CODE_TO_ID.keys())[list(NEED_CODE_TO_ID.values()).index(r['need_id'])]}: {r['weight']}" for r in top)
            print(f"  tagged {len(tag_rows)} needs  (top: {top_str})")

        # Polite rate limiting — Open Library asks for 1 req/sec
        time.sleep(1.2)

    print("\nDone.")


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    ingest_all(dry_run=dry_run)
