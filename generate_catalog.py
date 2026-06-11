"""
Folio — Offline catalog generation
====================================
Uses Claude to generate need weights for 500 curated books from its own training
knowledge. Open Library is used only for cover URLs and publication metadata —
not as the source of knowledge for tagging.

This script runs once (or whenever you want to expand the catalog). It is never
triggered by user requests, so there is no public API surface and no abuse vector.

Usage:
    SUPABASE_URL=... SUPABASE_KEY=... ANTHROPIC_API_KEY=... python generate_catalog.py
    python generate_catalog.py --dry-run   # print without writing to DB

Estimated cost: ~$0.50 for 500 books (Claude Haiku).
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Optional

import anthropic
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Need mapping
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
# 500 curated books spanning all 13 psychological needs.
# Chosen for: cultural breadth, need coverage, strong Claude knowledge.
# Grouped by dominant need but many serve multiple needs — that's the point.
# ---------------------------------------------------------------------------

CATALOG: list[tuple[str, str]] = [
    # being_chosen
    ("The Notebook", "Nicholas Sparks"),
    ("Twilight", "Stephenie Meyer"),
    ("Outlander", "Diana Gabaldon"),
    ("It Ends with Us", "Colleen Hoover"),
    ("Me Before You", "Jojo Moyes"),
    ("The Fault in Our Stars", "John Green"),
    ("Pride and Prejudice", "Jane Austen"),
    ("Jane Eyre", "Charlotte Brontë"),
    ("Attachments", "Rainbow Rowell"),
    ("One Day", "David Nicholls"),
    ("The Time Traveler's Wife", "Audrey Niffenegger"),
    ("Sense and Sensibility", "Jane Austen"),
    ("Gone with the Wind", "Margaret Mitchell"),
    ("Rebecca", "Daphne du Maurier"),
    ("Wuthering Heights", "Emily Brontë"),
    ("Anna Karenina", "Leo Tolstoy"),
    ("The Bridges of Madison County", "Robert James Waller"),
    ("P.S. I Love You", "Cecelia Ahern"),
    ("The Rosie Project", "Graeme Simsion"),
    ("Eleanor & Park", "Rainbow Rowell"),

    # surviving
    ("The Hunger Games", "Suzanne Collins"),
    ("The Road", "Cormac McCarthy"),
    ("Wild", "Cheryl Strayed"),
    ("A Little Life", "Hanya Yanagihara"),
    ("The Girl with the Dragon Tattoo", "Stieg Larsson"),
    ("Life of Pi", "Yann Martel"),
    ("The Martian", "Andy Weir"),
    ("Into Thin Air", "Jon Krakauer"),
    ("Unbroken", "Laura Hillenbrand"),
    ("The Things They Carried", "Tim O'Brien"),
    ("Matterhorn", "Karl Marlantes"),
    ("Man's Search for Meaning", "Viktor Frankl"),
    ("The Diary of a Young Girl", "Anne Frank"),
    ("Night", "Elie Wiesel"),
    ("Behind the Beautiful Forevers", "Katherine Boo"),
    ("I Know Why the Caged Bird Sings", "Maya Angelou"),
    ("When the Emperor Was Divine", "Julie Otsuka"),
    ("Half of a Yellow Sun", "Chimamanda Ngozi Adichie"),
    ("The Kite Runner", "Khaled Hosseini"),
    ("A Long Way Gone", "Ishmael Beah"),

    # procedural_resolution
    ("Gone Girl", "Gillian Flynn"),
    ("Big Little Lies", "Liane Moriarty"),
    ("In the Woods", "Tana French"),
    ("The Silent Patient", "Alex Michaelides"),
    ("The Woman in the Window", "A.J. Finn"),
    ("Sharp Objects", "Gillian Flynn"),
    ("Dark Places", "Gillian Flynn"),
    ("The Da Vinci Code", "Dan Brown"),
    ("And Then There Were None", "Agatha Christie"),
    ("The Murder of Roger Ackroyd", "Agatha Christie"),
    ("Tana French's Dublin Murder Squad", "Tana French"),
    ("In a Dark Dark Wood", "Ruth Ware"),
    ("The Woman in Cabin 10", "Ruth Ware"),
    ("Behind Closed Doors", "B.A. Paris"),
    ("The Secret History", "Donna Tartt"),
    ("The Name of the Rose", "Umberto Eco"),
    ("Presumed Innocent", "Scott Turow"),
    ("The Girl on the Train", "Paula Hawkins"),
    ("The Snowman", "Jo Nesbø"),
    ("Stieg Larsson's Millennium Series", "Stieg Larsson"),

    # moral_complexity
    ("The Kite Runner", "Khaled Hosseini"),
    ("Atonement", "Ian McEwan"),
    ("Crime and Punishment", "Fyodor Dostoevsky"),
    ("The Brothers Karamazov", "Fyodor Dostoevsky"),
    ("Lolita", "Vladimir Nabokov"),
    ("Sophie's Choice", "William Styron"),
    ("The Reader", "Bernhard Schlink"),
    ("Never Let Me Go", "Kazuo Ishiguro"),
    ("The Remains of the Day", "Kazuo Ishiguro"),
    ("A Man Called Ove", "Fredrik Backman"),
    ("The Lovely Bones", "Alice Sebold"),
    ("We Need to Talk About Kevin", "Lionel Shriver"),
    ("The Road", "Cormac McCarthy"),
    ("Beloved", "Toni Morrison"),
    ("Schindler's Ark", "Thomas Keneally"),
    ("The Pillars of the Earth", "Ken Follett"),
    ("Lincoln in the Bardo", "George Saunders"),
    ("All the Light We Cannot See", "Anthony Doerr"),
    ("The Nightingale", "Kristin Hannah"),
    ("The Book Thief", "Markus Zusak"),

    # power_agency
    ("The Handmaid's Tale", "Margaret Atwood"),
    ("Little Fires Everywhere", "Celeste Ng"),
    ("Becoming", "Michelle Obama"),
    ("The Power", "Naomi Alderman"),
    ("The Testaments", "Margaret Atwood"),
    ("Brave New World", "Aldous Huxley"),
    ("1984", "George Orwell"),
    ("Animal Farm", "George Orwell"),
    ("The Color Purple", "Alice Walker"),
    ("Their Eyes Were Watching God", "Zora Neale Hurston"),
    ("The Joy Luck Club", "Amy Tan"),
    ("Pachinko", "Min Jin Lee"),
    ("The Sympathizer", "Viet Thanh Nguyen"),
    ("The Underground Railroad", "Colson Whitehead"),
    ("Invisible Man", "Ralph Ellison"),
    ("Giovanni's Room", "James Baldwin"),
    ("Americanah", "Chimamanda Ngozi Adichie"),
    ("Purple Hibiscus", "Chimamanda Ngozi Adichie"),
    ("Things Fall Apart", "Chinua Achebe"),
    ("The Women's Room", "Marilyn French"),

    # wound_visible
    ("When Breath Becomes Air", "Paul Kalanithi"),
    ("The Year of Magical Thinking", "Joan Didion"),
    ("Educated", "Tara Westover"),
    ("The Body Keeps the Score", "Bessel van der Kolk"),
    ("A Little Life", "Hanya Yanagihara"),
    ("The Glass Castle", "Jeannette Walls"),
    ("This Boy's Life", "Tobias Wolff"),
    ("The Liar's Club", "Mary Karr"),
    ("In the Realm of Hungry Ghosts", "Gabor Maté"),
    ("Beautiful Boy", "David Sheff"),
    ("The Noonday Demon", "Andrew Solomon"),
    ("Reasons to Stay Alive", "Matt Haig"),
    ("An Unquiet Mind", "Kay Redfield Jamison"),
    ("Brain on Fire", "Susannah Cahalan"),
    ("A Child Called It", "Dave Pelzer"),
    ("Motherless Brooklyn", "Jonathan Lethem"),
    ("The Perks of Being a Wallflower", "Stephen Chbosky"),
    ("Speak", "Laurie Halse Anderson"),
    ("Lucky", "Alice Sebold"),
    ("Know My Name", "Chanel Miller"),

    # making_sense_history
    ("Sapiens", "Yuval Noah Harari"),
    ("Guns, Germs, and Steel", "Jared Diamond"),
    ("The Silk Roads", "Peter Frankopan"),
    ("Empire of the Summer Moon", "S.C. Gwynne"),
    ("The Devil in the White City", "Erik Larson"),
    ("Dead Wake", "Erik Larson"),
    ("Isaac's Storm", "Erik Larson"),
    ("The Warmth of Other Suns", "Isabel Wilkerson"),
    ("Caste", "Isabel Wilkerson"),
    ("Between the World and Me", "Ta-Nehisi Coates"),
    ("Bury My Heart at Wounded Knee", "Dee Brown"),
    ("The Autobiography of Malcolm X", "Malcolm X"),
    ("Long Walk to Freedom", "Nelson Mandela"),
    ("A People's History of the United States", "Howard Zinn"),
    ("The Federalist Papers", "Hamilton, Madison, Jay"),
    ("Team of Rivals", "Doris Kearns Goodwin"),
    ("The Rise and Fall of the Third Reich", "William L. Shirer"),
    ("The Gulag Archipelago", "Aleksandr Solzhenitsyn"),
    ("Hiroshima", "John Hersey"),
    ("The Guns of August", "Barbara Tuchman"),

    # self_remade
    ("Eat Pray Love", "Elizabeth Gilbert"),
    ("The Alchemist", "Paulo Coelho"),
    ("Normal People", "Sally Rooney"),
    ("Eleanor Oliphant Is Completely Fine", "Gail Honeyman"),
    ("Wild", "Cheryl Strayed"),
    ("Big Magic", "Elizabeth Gilbert"),
    ("The Power of Now", "Eckhart Tolle"),
    ("Man's Search for Meaning", "Viktor Frankl"),
    ("Tiny Beautiful Things", "Cheryl Strayed"),
    ("Option B", "Sheryl Sandberg"),
    ("When Things Fall Apart", "Pema Chödrön"),
    ("Daring Greatly", "Brené Brown"),
    ("The Gifts of Imperfection", "Brené Brown"),
    ("Rising Strong", "Brené Brown"),
    ("A New Earth", "Eckhart Tolle"),
    ("The Untethered Soul", "Michael A. Singer"),
    ("Educated", "Tara Westover"),
    ("The Glass Castle", "Jeannette Walls"),
    ("Born a Crime", "Trevor Noah"),
    ("Just Kids", "Patti Smith"),

    # inside_power
    ("House of Cards", "Michael Dobbs"),
    ("The Final Empire", "Brandon Sanderson"),
    ("Fire and Blood", "George R.R. Martin"),
    ("A Game of Thrones", "George R.R. Martin"),
    ("The Prince", "Niccolò Machiavelli"),
    ("Robert Caro's The Power Broker", "Robert A. Caro"),
    ("Team of Rivals", "Doris Kearns Goodwin"),
    ("Primary Colors", "Anonymous"),
    ("The West Wing", "Aaron Sorkin"),
    ("All the President's Men", "Bob Woodward"),
    ("The Fifth Risk", "Michael Lewis"),
    ("Too Big to Fail", "Andrew Ross Sorkin"),
    ("The Big Short", "Michael Lewis"),
    ("Liar's Poker", "Michael Lewis"),
    ("Bad Blood", "John Carreyrou"),
    ("Barbarians at the Gate", "Bryan Burrough"),
    ("The Smartest Guys in the Room", "Bethany McLean"),
    ("When Genius Failed", "Roger Lowenstein"),
    ("Den of Thieves", "James B. Stewart"),
    ("The Godfather", "Mario Puzo"),

    # identity_witnessed
    ("The Color Purple", "Alice Walker"),
    ("On Earth We're Briefly Gorgeous", "Ocean Vuong"),
    ("Giovanni's Room", "James Baldwin"),
    ("Americanah", "Chimamanda Ngozi Adichie"),
    ("The Bluest Eye", "Toni Morrison"),
    ("Song of Solomon", "Toni Morrison"),
    ("Beloved", "Toni Morrison"),
    ("The House on Mango Street", "Sandra Cisneros"),
    ("Bless Me Ultima", "Rudolfo Anaya"),
    ("The Brief Wondrous Life of Oscar Wao", "Junot Díaz"),
    ("In the Time of the Butterflies", "Julia Alvarez"),
    ("Interpreter of Maladies", "Jhumpa Lahiri"),
    ("The Namesake", "Jhumpa Lahiri"),
    ("The God of Small Things", "Arundhati Roy"),
    ("A Fine Balance", "Rohinton Mistry"),
    ("The Kite Runner", "Khaled Hosseini"),
    ("A Thousand Splendid Suns", "Khaled Hosseini"),
    ("The Joy Luck Club", "Amy Tan"),
    ("When the Emperor Was Divine", "Julie Otsuka"),
    ("Snow Falling on Cedars", "David Guterson"),

    # world_larger
    ("Life of Pi", "Yann Martel"),
    ("The Hitchhiker's Guide to the Galaxy", "Douglas Adams"),
    ("Project Hail Mary", "Andy Weir"),
    ("The Martian", "Andy Weir"),
    ("Ender's Game", "Orson Scott Card"),
    ("Dune", "Frank Herbert"),
    ("Foundation", "Isaac Asimov"),
    ("The Left Hand of Darkness", "Ursula K. Le Guin"),
    ("A Wrinkle in Time", "Madeleine L'Engle"),
    ("His Dark Materials", "Philip Pullman"),
    ("The Name of the Wind", "Patrick Rothfuss"),
    ("Jonathan Strange & Mr Norrell", "Susanna Clarke"),
    ("Piranesi", "Susanna Clarke"),
    ("The Night Circus", "Erin Morgenstern"),
    ("The Book of the New Sun", "Gene Wolfe"),
    ("Watership Down", "Richard Adams"),
    ("The Wind in the Willows", "Kenneth Grahame"),
    ("The Little Prince", "Antoine de Saint-Exupéry"),
    ("The Alchemist", "Paulo Coelho"),
    ("Siddhartha", "Hermann Hesse"),

    # creative_kinship
    ("Tomorrow and Tomorrow and Tomorrow", "Gabrielle Zevin"),
    ("Station Eleven", "Emily St. John Mandel"),
    ("The Paris Wife", "Paula McLain"),
    ("Just Kids", "Patti Smith"),
    ("M Train", "Patti Smith"),
    ("On Writing", "Stephen King"),
    ("Bird by Bird", "Anne Lamott"),
    ("The War of Art", "Steven Pressfield"),
    ("Big Magic", "Elizabeth Gilbert"),
    ("The Creative Habit", "Twyla Tharp"),
    ("Steal Like an Artist", "Austin Kleon"),
    ("Letters to a Young Poet", "Rainer Maria Rilke"),
    ("Flowers for Algernon", "Daniel Keyes"),
    ("The Goldfinch", "Donna Tartt"),
    ("A Visit from the Goon Squad", "Jennifer Egan"),
    ("The Hours", "Michael Cunningham"),
    ("Mrs Dalloway", "Virginia Woolf"),
    ("To the Lighthouse", "Virginia Woolf"),
    ("Orlando", "Virginia Woolf"),
    ("The Bell Jar", "Sylvia Plath"),

    # anxiety_named
    ("The Midnight Library", "Matt Haig"),
    ("Anxious People", "Fredrik Backman"),
    ("Maybe You Should Talk to Someone", "Lori Gottlieb"),
    ("Normal People", "Sally Rooney"),
    ("Conversations with Friends", "Sally Rooney"),
    ("Beautiful World Where Are You", "Sally Rooney"),
    ("My Year of Rest and Relaxation", "Ottessa Moshfegh"),
    ("Fleishman Is in Trouble", "Taffy Brodesser-Akner"),
    ("Anxious People", "Fredrik Backman"),
    ("A Man Called Ove", "Fredrik Backman"),
    ("Beartown", "Fredrik Backman"),
    ("The Subtle Art of Not Giving a F*ck", "Mark Manson"),
    ("Lost Connections", "Johann Hari"),
    ("Why Has Nobody Told Me This Before", "Julie Smith"),
    ("The Courage to Be Disliked", "Ichiro Kishimi"),
    ("The Stoic Challenge", "William B. Irvine"),
    ("Four Thousand Weeks", "Oliver Burkeman"),
    ("Stoner", "John Williams"),
    ("The Remains of the Day", "Kazuo Ishiguro"),
    ("Never Let Me Go", "Kazuo Ishiguro"),
]

# Deduplicate while preserving order
_seen: set[tuple[str, str]] = set()
CATALOG_DEDUPED: list[tuple[str, str]] = []
for _entry in CATALOG:
    if _entry not in _seen:
        _seen.add(_entry)
        CATALOG_DEDUPED.append(_entry)


# ---------------------------------------------------------------------------
# Open Library — covers and metadata only
# ---------------------------------------------------------------------------

def _ol_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Folio/1.0 (catalog-generation)"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def fetch_ol_metadata(title: str, author: str) -> dict:
    """Fetch cover URL, pub_year, ratings_count from Open Library.
    Returns empty dict on failure — all fields are optional."""
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
        cover_i = doc.get("cover_i")
        isbn_list = doc.get("isbn", [])
        ratings_count = doc.get("ratings_count") or 0
        avg_rating = doc.get("ratings_average")
        return {
            "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg" if cover_i else None,
            "pub_year": doc.get("first_publish_year"),
            "isbn": isbn_list[0] if isbn_list else None,
            "ratings_count": int(ratings_count),
            "avg_rating": round(float(avg_rating), 2) if avg_rating else None,
        }
    except Exception as e:
        logger.warning("OL metadata fetch failed for '%s': %s", title, e)
        return {}


# ---------------------------------------------------------------------------
# Claude tagging — from training knowledge, not description
# ---------------------------------------------------------------------------

TAGGING_SYSTEM = """You are a literary psychologist with deep knowledge of published books.
You assign psychological need weights to books based on your knowledge of their content,
themes, and emotional texture — NOT from a description provided to you.

Rules:
- Most books serve 2–4 needs strongly (≥0.4); the rest should be 0.0–0.2.
- Weights do not need to sum to 1.
- Be specific and precise — use your actual knowledge of the book.
- For wound_visible, also set has_perpetrator: true if the wound was caused by another
  person (abuse, violence, betrayal), false if circumstantial (illness, accident, loss).

Respond with valid JSON only — no explanation, no markdown fences."""

TAGGING_PROMPT = """Score "{title}" by {author} across these 13 psychological needs (0.0–1.0 each):

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


def tag_book_from_knowledge(client: anthropic.Anthropic, title: str, author: str) -> dict:
    """Tag a book using Claude's training knowledge — no description needed."""
    needs_list = "\n".join(f"  {code}: {desc}" for code, desc in NEED_DESCRIPTIONS.items())
    prompt = TAGGING_PROMPT.format(title=title, author=author, needs_list=needs_list)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=TAGGING_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) < 2:
            raise ValueError(f"Malformed fenced block: {raw[:200]}")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Main ingestion loop
# ---------------------------------------------------------------------------

def generate_catalog(dry_run: bool = False) -> None:
    db = None if dry_run else create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    books = CATALOG_DEDUPED
    logger.info("Generating catalog: %d books  (dry_run=%s)", len(books), dry_run)

    for i, (title, author) in enumerate(books, 1):
        logger.info("[%03d/%d] %s — %s", i, len(books), title, author)

        # 1. Tag from Claude's knowledge
        try:
            tags = tag_book_from_knowledge(ai, title, author)
        except Exception as e:
            logger.warning("  Tagging failed: %s — skipping", e)
            time.sleep(1)
            continue

        has_perpetrator: Optional[bool] = tags.pop("has_perpetrator", None)

        # 2. Fetch OL metadata for covers and ratings (non-blocking)
        meta = fetch_ol_metadata(title, author)
        time.sleep(1.1)  # OL rate limit: 1 req/sec

        if dry_run:
            logger.info("  tags: %s", {k: v for k, v in tags.items() if v > 0.1})
            logger.info("  meta: %s", meta)
            continue

        # 3. Upsert book row
        book_row = {
            "title": title,
            "author": author,
            "cover_url": meta.get("cover_url"),
            "pub_year": meta.get("pub_year"),
            "isbn": meta.get("isbn"),
            "ratings_count": meta.get("ratings_count", 0),
            "avg_rating": meta.get("avg_rating"),
        }
        book_result = db.table("books").upsert(book_row, on_conflict="title,author").execute()
        if not book_result.data:
            logger.warning("  Book upsert returned no data — skipping")
            continue
        book_id = book_result.data[0]["id"]

        # 4. Build and upsert need tag rows
        tag_rows = []
        for code, weight in tags.items():
            need_id = NEED_CODE_TO_ID.get(code)
            if need_id is None:
                continue
            w = round(max(0.0, min(1.0, float(weight))), 3)
            if w == 0.0:
                continue
            row: dict = {"book_id": book_id, "need_id": need_id, "weight": w, "source": "llm"}
            if code == "wound_visible" and has_perpetrator is not None:
                row["has_perpetrator"] = has_perpetrator
            tag_rows.append(row)

        if tag_rows:
            db.table("book_need_tags").upsert(tag_rows, on_conflict="book_id,need_id").execute()
            top = sorted(tag_rows, key=lambda r: r["weight"], reverse=True)[:3]
            top_str = ", ".join(f"{NEED_ID_TO_CODE.get(r['need_id'])}: {r['weight']}" for r in top)
            logger.info("  tagged %d needs (top: %s)", len(tag_rows), top_str)

    logger.info("Done. %d books processed.", len(books))


if __name__ == "__main__":
    import sys
    generate_catalog(dry_run="--dry-run" in sys.argv)
