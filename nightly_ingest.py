"""
Folio — Nightly book request ingestion
=========================================
Reads the book_requests table, finds the most-requested titles not yet in the
catalog, and ingests them using the same confidence-based hybrid approach:
  - Claude tags from training knowledge first
  - If the book was published after the training cutoff OR Open Library has a
    substantial description, supplement with OL data and re-tag

This script is intended to run as a scheduled job (Railway cron, Heroku Scheduler,
or a cron tab). It is never triggered by user requests.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... ANTHROPIC_API_KEY=... python nightly_ingest.py
    python nightly_ingest.py --dry-run
    python nightly_ingest.py --limit 20   # process at most 20 books per run
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import anthropic
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Claude's approximate training cutoff. Books published after this date are
# outside Claude's training data — always supplement with OL description.
TRAINING_CUTOFF_YEAR = 2024

# OL description length threshold: below this we consider the book under-documented
# and fall back to Claude's knowledge alone rather than feeding a thin description.
MIN_DESCRIPTION_LENGTH = 100

# Minimum request count to be included in a nightly run
MIN_REQUEST_COUNT = 2

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

NEED_ID_TO_CODE: dict[int, str] = {v: k for k, v in NEED_CODE_TO_ID.items()}

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
# Open Library helpers
# ---------------------------------------------------------------------------

def _ol_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Folio/1.0 (nightly-ingest)"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def fetch_ol_full(title: str, author: str) -> dict:
    """Fetch full OL metadata including description. Returns empty dict on failure."""
    try:
        q = urllib.parse.urlencode({
            "title": title, "author": author, "limit": 1,
            "fields": "key,title,author_name,cover_i,first_publish_year,ratings_count,ratings_average,isbn",
        })
        data = _ol_get(f"https://openlibrary.org/search.json?{q}")
        docs = data.get("docs", [])
        if not docs:
            return {}
        doc = docs[0]

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
                    time.sleep(1.1)
                except Exception:
                    pass

        cover_i = doc.get("cover_i")
        isbn_list = doc.get("isbn", [])
        ratings_count = doc.get("ratings_count") or 0
        avg_rating = doc.get("ratings_average")
        authors = doc.get("author_name", [])

        return {
            "title": doc.get("title", title),
            "author": ", ".join(authors) if authors else author,
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg" if cover_i else None,
            "pub_year": doc.get("first_publish_year"),
            "isbn": isbn_list[0] if isbn_list else None,
            "ratings_count": int(ratings_count),
            "avg_rating": round(float(avg_rating), 2) if avg_rating else None,
            "description": description,
        }
    except Exception as e:
        logger.warning("OL fetch failed for '%s': %s", title, e)
        return {}


# ---------------------------------------------------------------------------
# Confidence-based tagging
# ---------------------------------------------------------------------------

SYSTEM_FROM_KNOWLEDGE = """You are a literary psychologist with deep knowledge of published books.
Score the book using your training knowledge of its content and themes.
Respond with valid JSON only — no explanation, no markdown fences."""

SYSTEM_WITH_DESCRIPTION = """You are a literary psychologist. Score the book using both your
knowledge of it and the description provided. If the description contradicts your knowledge,
trust the description.
Respond with valid JSON only — no explanation, no markdown fences."""

TAGGING_PROMPT_KNOWLEDGE = """Score "{title}" by {author} across these 13 psychological needs (0.0–1.0 each):

{needs_list}

Return JSON in exactly this shape:
{{
  "being_chosen": 0.0, "surviving": 0.0, "procedural_resolution": 0.0,
  "moral_complexity": 0.0, "power_agency": 0.0, "wound_visible": 0.0,
  "making_sense_history": 0.0, "self_remade": 0.0, "inside_power": 0.0,
  "identity_witnessed": 0.0, "world_larger": 0.0, "creative_kinship": 0.0,
  "anxiety_named": 0.0, "has_perpetrator": false
}}"""

TAGGING_PROMPT_WITH_DESC = """Book: "{title}" by {author}

Description: {description}

Score this book across these 13 psychological needs (0.0–1.0 each):

{needs_list}

Return JSON in exactly this shape:
{{
  "being_chosen": 0.0, "surviving": 0.0, "procedural_resolution": 0.0,
  "moral_complexity": 0.0, "power_agency": 0.0, "wound_visible": 0.0,
  "making_sense_history": 0.0, "self_remade": 0.0, "inside_power": 0.0,
  "identity_witnessed": 0.0, "world_larger": 0.0, "creative_kinship": 0.0,
  "anxiety_named": 0.0, "has_perpetrator": false
}}"""


def _parse_tags(raw: str) -> dict:
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) < 2:
            raise ValueError(f"Malformed fenced block: {raw[:200]}")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def tag_book(
    client: anthropic.Anthropic,
    title: str,
    author: str,
    pub_year: Optional[int],
    description: Optional[str],
) -> tuple[dict, str]:
    """Tag a book using the confidence-based hybrid approach.

    Decision logic:
      - Recent book (pub_year > TRAINING_CUTOFF_YEAR): must use description if available
      - Older book with rich description (len > threshold): supplement with description
      - Otherwise: tag from Claude's training knowledge alone

    Returns (tags_dict, source_label).
    """
    needs_list = "\n".join(f"  {code}: {desc}" for code, desc in NEED_DESCRIPTIONS.items())
    use_description = (
        description
        and len(description) >= MIN_DESCRIPTION_LENGTH
        and (pub_year is None or pub_year > TRAINING_CUTOFF_YEAR or len(description) >= MIN_DESCRIPTION_LENGTH)
    )

    if use_description and (pub_year or 0) > TRAINING_CUTOFF_YEAR:
        system = SYSTEM_WITH_DESCRIPTION
        prompt = TAGGING_PROMPT_WITH_DESC.format(
            title=title, author=author,
            description=description[:1500],  # cap to avoid token bloat
            needs_list=needs_list,
        )
        source = "llm+public_data"
    elif use_description:
        system = SYSTEM_WITH_DESCRIPTION
        prompt = TAGGING_PROMPT_WITH_DESC.format(
            title=title, author=author,
            description=description[:1500],
            needs_list=needs_list,
        )
        source = "llm+public_data"
    else:
        system = SYSTEM_FROM_KNOWLEDGE
        prompt = TAGGING_PROMPT_KNOWLEDGE.format(title=title, author=author, needs_list=needs_list)
        source = "llm"

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_tags(message.content[0].text.strip()), source


# ---------------------------------------------------------------------------
# Main nightly loop
# ---------------------------------------------------------------------------

def run_nightly(dry_run: bool = False, limit: int = 50) -> None:
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Fetch most-requested books not yet in catalog
    requests = (
        db.table("book_requests")
        .select("title, author, request_count")
        .eq("status", "pending")
        .gte("request_count", MIN_REQUEST_COUNT)
        .order("request_count", desc=True)
        .limit(limit)
        .execute()
        .data
    )

    if not requests:
        logger.info("No pending book requests meeting threshold. Nothing to do.")
        return

    logger.info("Processing %d requested books  (dry_run=%s)", len(requests), dry_run)

    for req in requests:
        title = req["title"]
        author = req.get("author") or ""
        logger.info("  %s — %s (%d requests)", title, author, req["request_count"])

        # 1. Fetch OL metadata (covers + description for confidence check)
        meta = fetch_ol_full(title, author)
        time.sleep(1.1)

        pub_year = meta.get("pub_year")
        description = meta.get("description")

        # 2. Tag with confidence-based hybrid
        try:
            tags, source = tag_book(ai, title, author, pub_year, description)
        except Exception as e:
            logger.warning("  Tagging failed: %s — skipping", e)
            if not dry_run:
                db.table("book_requests").update({"status": "failed"}).eq("title", title).execute()
            continue

        has_perpetrator: Optional[bool] = tags.pop("has_perpetrator", None)

        if dry_run:
            logger.info("  source: %s | tags: %s", source, {k: v for k, v in tags.items() if v > 0.1})
            continue

        # 3. Upsert book
        book_row = {
            "title": meta.get("title", title),
            "author": meta.get("author", author) or author,
            "cover_url": meta.get("cover_url"),
            "pub_year": pub_year,
            "isbn": meta.get("isbn"),
            "ratings_count": meta.get("ratings_count", 0),
            "avg_rating": meta.get("avg_rating"),
            "description": description,
        }
        book_result = db.table("books").upsert(book_row, on_conflict="title,author").execute()
        if not book_result.data:
            logger.warning("  Book upsert returned no data — skipping")
            continue
        book_id = book_result.data[0]["id"]

        # 4. Insert need tags
        tag_rows = []
        for code, weight in tags.items():
            need_id = NEED_CODE_TO_ID.get(code)
            if need_id is None:
                continue
            w = round(max(0.0, min(1.0, float(weight))), 3)
            if w == 0.0:
                continue
            row: dict = {"book_id": book_id, "need_id": need_id, "weight": w, "source": source}
            if code == "wound_visible" and has_perpetrator is not None:
                row["has_perpetrator"] = has_perpetrator
            tag_rows.append(row)

        if tag_rows:
            db.table("book_need_tags").upsert(tag_rows, on_conflict="book_id,need_id").execute()

        # 5. Mark request as ingested
        db.table("book_requests").update({"status": "ingested"}).eq("title", title).execute()

        top = sorted(tag_rows, key=lambda r: r["weight"], reverse=True)[:3]
        top_str = ", ".join(f"{NEED_ID_TO_CODE.get(r['need_id'])}: {r['weight']}" for r in top)
        logger.info("  ingested  source=%s  top: %s", source, top_str)

    logger.info("Nightly ingest complete.")


if __name__ == "__main__":
    import sys
    dry_run = "--dry-run" in sys.argv
    limit_arg = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), 50)
    run_nightly(dry_run=dry_run, limit=limit_arg)
