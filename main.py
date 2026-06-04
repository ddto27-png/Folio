"""
Folio — FastAPI backend
=======================
Five endpoints that connect the scoring engine (scoring.py) to the Supabase database
and expose an HTTP API the Next.js frontend consumes.

Endpoints:
  GET  /books/search              — search catalog + Open Library live
  POST /books/find-or-create      — add a new book to the catalog and tag it with Claude
  POST /reads                     — log a read event (JWT-authenticated)
  GET  /recommendations           — run full scoring pipeline and return top books (JWT-authenticated)
  GET  /wishlist                  — return user's saved books ranked by match score (JWT-authenticated)
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt as pyjwt
import anthropic
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from supabase import create_client, Client

from scoring import (
    ReadEvent,
    ReadingState,
    BookProfile,
    NeedAffinity,
    compute_all_affinities,
    modulate_for_state,
    match_score,
    build_why_prompt,
    NEEDS,
)

# ---------------------------------------------------------------------------
# Supabase + Anthropic clients (lazy singletons)
# ---------------------------------------------------------------------------
# Both clients are created on first use so the app can start up even if the
# environment variables aren't set yet (useful during local development).

_supabase: Optional[Client] = None
_anthropic: Optional[anthropic.Anthropic] = None


def get_supabase() -> Client:
    """Returns the shared Supabase client, creating it on first call.
    Reads SUPABASE_URL and SUPABASE_KEY from environment variables."""
    global _supabase
    if _supabase is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _supabase = create_client(url, key)
    return _supabase


def get_anthropic() -> anthropic.Anthropic:
    """Returns the shared Anthropic client, creating it on first call.
    Reads ANTHROPIC_API_KEY from environment variables."""
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic


# ---------------------------------------------------------------------------
# Book tagging helpers (used by the find-or-create endpoint)
# ---------------------------------------------------------------------------

# Maps the need code strings used in scoring.py to the integer IDs in the
# Supabase 'needs' table. Used when inserting book_need_tags rows.
NEED_CODE_TO_ID: dict[str, int] = {
    "being_chosen": 1, "surviving": 2, "procedural_resolution": 3,
    "moral_complexity": 4, "power_agency": 5, "wound_visible": 6,
    "making_sense_history": 7, "self_remade": 8, "inside_power": 9,
    "identity_witnessed": 10, "world_larger": 11, "creative_kinship": 12,
    "anxiety_named": 13,
}

# Human-readable descriptions of each need, passed to Claude Haiku in the
# tagging prompt so it understands what each code means.
_NEED_DESCRIPTIONS = {
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

# System prompt for Claude Haiku tagging. Instructs the model to return
# only valid JSON with a 0–1 weight for each of the 13 needs.
_TAGGING_SYSTEM = (
    "You are a literary psychologist. Given a book's title, author, and description, "
    "assign weights (0.0-1.0) reflecting how strongly it serves each of 13 psychological needs. "
    "Most books serve 2-4 needs strongly (>=0.4); the rest should be 0.0-0.2. "
    "For wound_visible also set has_perpetrator: true if the wound was caused by another person. "
    "Respond with valid JSON only - no explanation, no markdown fences."
)

# Template filled in per book and sent to Claude Haiku as the user message.
_TAGGING_TEMPLATE = """Book: "{title}" by {author}
Description: {description}

Score across these 13 needs (0.0-1.0 each):
{needs_list}

Return JSON: {{"being_chosen":0.0,"surviving":0.0,"procedural_resolution":0.0,"moral_complexity":0.0,"power_agency":0.0,"wound_visible":0.0,"making_sense_history":0.0,"self_remade":0.0,"inside_power":0.0,"identity_witnessed":0.0,"world_larger":0.0,"creative_kinship":0.0,"anxiety_named":0.0,"has_perpetrator":false}}"""


def _tag_book(client: anthropic.Anthropic, title: str, author: str, description: str) -> dict:
    """Calls Claude Haiku to assign psychological need weights to a book.
    Returns a dict with one key per need (0–1 float) plus 'has_perpetrator' (bool).
    Strips markdown fences in case the model wraps its JSON response in them."""
    needs_list = "\n".join(f"  {k}: {v}" for k, v in _NEED_DESCRIPTIONS.items())
    prompt = _TAGGING_TEMPLATE.format(
        title=title, author=author,
        description=description or "(infer from title and author)",
        needs_list=needs_list,
    )
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=_TAGGING_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # Strip ```json ... ``` fences if the model added them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _ol_get(url: str) -> dict:
    """Makes a GET request to the Open Library API and returns the JSON response.
    Sets a Folio User-Agent header as Open Library requires identification."""
    req = urllib.request.Request(url, headers={"User-Agent": "Folio/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Folio", version="0.1.0")

# ---------------------------------------------------------------------------
# Auth — JWT validation
# ---------------------------------------------------------------------------
# Verifies the Supabase JWT sent by the frontend on every user-specific request.
# Extracts the user's UUID from the token so endpoints never trust the URL.
# SUPABASE_JWT_SECRET is in your Supabase dashboard → Settings → API → JWT Secret.

_bearer = HTTPBearer(auto_error=False)

def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = pyjwt.decode(
            credentials.credentials,
            os.environ["SUPABASE_JWT_SECRET"],
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload["sub"]  # Supabase stores the user UUID here
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
# Pydantic models define the shape of request bodies and response payloads.
# FastAPI validates incoming data against these automatically.

class ReadEventRequest(BaseModel):
    """Body for POST /reads — what a user read and how they felt."""
    book_id: str
    signal_type: str              # e.g. "star_5", "abandoned", "re_read"
    pct_read: float = 1.0         # 0.0–1.0
    emotional_state: int          # 1 (crisis) – 5 (joyful)
    post_emotional_state: Optional[int] = None  # how the reader felt after finishing (1–5)
    occurred_at: Optional[datetime] = None  # if omitted, defaults to now
    review_text: Optional[str] = None


class RecommendationResponse(BaseModel):
    """One book recommendation returned by GET /recommendations."""
    book_id: str
    title: str
    author: Optional[str]
    cover_url: Optional[str]
    match_score: float        # 0–1, how well this book matches the reader right now
    top_need_ids: list[int]   # the 1–2 needs driving this match (for NeedBadge display)
    why_text: str             # Claude-generated explanation of why this book fits


class WishlistItemResponse(BaseModel):
    """One item from the user's wishlist, returned by GET /wishlist."""
    book_id: str
    title: str
    author: Optional[str]
    cover_url: Optional[str]
    match_score: Optional[float]
    rank: Optional[int]              # position in the wishlist by current match score
    need_ids_matched: Optional[list[int]]


class BookSearchResult(BaseModel):
    """One result from GET /books/search — could be from our catalog or Open Library."""
    id: Optional[str]       # None if the book isn't in our catalog yet
    title: str
    author: Optional[str]
    cover_url: Optional[str]
    pub_year: Optional[int]
    in_catalog: bool        # True = already in our DB; False = from Open Library
    ol_key: Optional[str]   # Open Library work key (e.g. "/works/OL123W"), used to fetch description


class FindOrCreateBookRequest(BaseModel):
    """Body for POST /books/find-or-create — minimal book metadata from the frontend."""
    title: str
    author: Optional[str] = None
    cover_url: Optional[str] = None
    pub_year: Optional[int] = None
    ol_key: Optional[str] = None   # if provided, we fetch the description from Open Library


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_user_read_events(db: Client, user_id: str) -> list[ReadEvent]:
    """Pulls all read events for a user from the 'reads' table and enriches
    each one with the book's need weights from 'book_need_tags'.

    Steps:
      1. Fetch all read rows for the user
      2. Collect all unique book IDs from those reads
      3. Fetch need tags for those books
      4. Build a lookup: book_id → {need_code: weight}
      5. Assemble ReadEvent objects with the enriched weights
    """
    rows = (
        db.table("reads")
        .select("book_id, signal_type, pct_read, emotional_state, post_emotional_state, occurred_at")
        .eq("user_id", user_id)
        .order("occurred_at", desc=False)
        .execute()
        .data
    )
    if not rows:
        return []

    book_ids = list({r["book_id"] for r in rows})
    tag_rows = (
        db.table("book_need_tags")
        .select("book_id, need_id, weight")
        .in_("book_id", book_ids)
        .execute()
        .data
    )

    # need_id (integer in DB) → need code string used by scoring engine
    need_codes = (
        db.table("needs")
        .select("id, code")
        .execute()
        .data
    )
    id_to_code = {n["id"]: n["code"] for n in need_codes}

    # Build per-book need weight lookup
    book_weights: dict[str, dict[str, float]] = {}
    for tag in tag_rows:
        bw = book_weights.setdefault(tag["book_id"], {})
        code = id_to_code.get(tag["need_id"])
        if code:
            bw[code] = float(tag["weight"])

    events: list[ReadEvent] = []
    for r in rows:
        occurred = datetime.fromisoformat(r["occurred_at"])
        # Ensure timezone-aware so scoring engine comparisons work correctly
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        post_state = r.get("post_emotional_state")
        events.append(
            ReadEvent(
                book_id=r["book_id"],
                signal_type=r["signal_type"],
                pct_read=float(r["pct_read"]),
                emotional_state=int(r["emotional_state"]),
                post_emotional_state=int(post_state) if post_state is not None else None,
                occurred_at=occurred,
                book_need_weights=book_weights.get(r["book_id"], {}),
            )
        )
    return events


def _fetch_current_reading_state(db: Client, user_id: str) -> ReadingState:
    """Fetches the user's current emotional state from 'reading_state'.
    Falls back to a neutral state (3 = just okay) if none is recorded.
    Converts active_need_ids from integer DB IDs to the need code strings
    that the scoring engine expects."""
    row = (
        db.table("reading_state")
        .select("emotional_state, active_need_ids, captured_at")
        .eq("user_id", user_id)
        .eq("is_current", True)
        .limit(1)
        .execute()
        .data
    )
    if not row:
        return ReadingState(emotional_state=3, captured_at=datetime.now(timezone.utc))

    r = row[0]
    captured = datetime.fromisoformat(r["captured_at"])
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)

    # Convert integer need IDs from the DB to code strings for scoring
    active_ids: list[int] = r.get("active_need_ids") or []
    if active_ids:
        code_rows = (
            db.table("needs")
            .select("id, code")
            .in_("id", active_ids)
            .execute()
            .data
        )
        active_codes = [c["code"] for c in code_rows]
    else:
        active_codes = []

    return ReadingState(
        emotional_state=int(r["emotional_state"]),
        active_need_ids=active_codes,
        captured_at=captured,
    )


def _generate_why_text(
    top_needs: list[str],
    book_title: str,
    book_description: str,
    persona_label: str = "a thoughtful reader",
) -> str:
    """Calls Claude Haiku to generate a personalised 2-sentence explanation of
    why this book matches this reader. Uses build_why_prompt() from scoring.py
    to construct the prompt, then passes it to Claude Haiku (max 120 tokens).
    The result is shown as the italic quote on each BookCard in the frontend."""
    prompt = build_why_prompt(persona_label, top_needs, book_title, book_description)
    client = get_anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# Endpoint: Book search (catalog + Open Library)
# ---------------------------------------------------------------------------

@app.get("/books/search", response_model=list[BookSearchResult])
async def search_books(q: str, limit: int = 8):
    """Search for books by title. Returns up to `limit` results from two sources:

    1. Our Supabase catalog (ilike search on title) — shown first.
       These books already have need tags and can be logged immediately.
    2. Open Library API — fills remaining slots if the catalog doesn't have enough matches.
       These results have id=None and in_catalog=False; selecting one triggers find-or-create.

    Results from both sources are deduped by title (case-insensitive).
    Open Library is queried with their search.json endpoint, requesting only
    the fields we need (key, title, author_name, cover_i, first_publish_year).
    """
    if len(q.strip()) < 2:
        return []

    db = get_supabase()

    # Search our catalog first — these results come back with real IDs
    catalog = (
        db.table("books")
        .select("id, title, author, cover_url, pub_year")
        .ilike("title", f"%{q}%")
        .limit(limit)
        .execute()
        .data
    )
    catalog_titles = {r["title"].lower() for r in catalog}
    results: list[dict] = [
        {**r, "in_catalog": True, "ol_key": None} for r in catalog
    ]

    # Fill remaining slots from Open Library (live external API call)
    remaining = limit - len(results)
    if remaining > 0:
        try:
            qs = urllib.parse.urlencode({
                "q": q, "limit": remaining + 5,  # fetch a few extra to account for dedup
                "fields": "key,title,author_name,cover_i,first_publish_year",
            })
            data = _ol_get(f"https://openlibrary.org/search.json?{qs}")
            for doc in data.get("docs", []):
                title = doc.get("title", "")
                if title.lower() in catalog_titles:
                    continue  # skip duplicates already in our catalog
                authors = doc.get("author_name", [])
                cover_i = doc.get("cover_i")
                results.append({
                    "id": None,   # not in our DB yet
                    "title": title,
                    "author": ", ".join(authors[:2]) if authors else None,
                    "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None,
                    "pub_year": doc.get("first_publish_year"),
                    "in_catalog": False,
                    "ol_key": doc.get("key"),  # e.g. "/works/OL123W"
                })
                catalog_titles.add(title.lower())
                if len(results) >= limit:
                    break
        except Exception:
            pass  # If Open Library is down, just return catalog results

    return results[:limit]


# ---------------------------------------------------------------------------
# Endpoint: Find or create a book (adds to catalog + tags via Claude)
# ---------------------------------------------------------------------------

@app.post("/books/find-or-create")
async def find_or_create_book(body: FindOrCreateBookRequest):
    """Ensure a book exists in our catalog. Called when the user selects a book
    from the onboarding search that isn't already in our DB (in_catalog=False).

    Steps:
      1. Check if a book with this title already exists (ilike match to handle
         minor differences in capitalisation).
      2. If not, fetch its description from Open Library using the ol_key.
      3. Insert the book into the 'books' table.
      4. Tag the book with Claude Haiku (assign 0–1 weights for all 13 needs).
      5. Insert the tags into 'book_need_tags' so it can be scored immediately.

    Returns the book row (id, title, author, cover_url).
    Tagging errors are silently swallowed — the book is still usable, just
    without need tags until the tags are added in a background process.
    """
    db = get_supabase()

    # Return existing book if we already have it (avoid duplicates)
    existing = (
        db.table("books")
        .select("id, title, author, cover_url, pub_year")
        .ilike("title", body.title)
        .limit(1)
        .execute()
        .data
    )
    if existing:
        return existing[0]

    # Fetch the book description from Open Library if we have a work key.
    # The description field can be a plain string or a {"type","value"} object.
    description: Optional[str] = None
    if body.ol_key:
        try:
            work = _ol_get(f"https://openlibrary.org{body.ol_key}.json")
            raw = work.get("description")
            description = raw.get("value") if isinstance(raw, dict) else raw
        except Exception:
            pass  # description is optional; scoring still works without it

    # Insert the book with whatever metadata we have
    row = {
        "title": body.title,
        "author": body.author,
        "cover_url": body.cover_url,
        "pub_year": body.pub_year,
        "description": description,
    }
    result = db.table("books").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create book")

    book = result.data[0]
    book_id = book["id"]

    # Tag the new book with Claude Haiku — this runs synchronously because the
    # user is about to log this book and we need the tags for scoring to work.
    try:
        tags = _tag_book(get_anthropic(), body.title, body.author or "", description or "")
        has_perpetrator = tags.pop("has_perpetrator", None)
        tag_rows = []
        for code, weight in tags.items():
            need_id = NEED_CODE_TO_ID.get(code)
            if not need_id:
                continue
            w = round(max(0.0, min(1.0, float(weight))), 3)
            if w == 0.0:
                continue  # don't store zero-weight tags
            entry = {"book_id": book_id, "need_id": need_id, "weight": w, "source": "llm"}
            # has_perpetrator is stored only on the wound_visible tag
            if code == "wound_visible" and has_perpetrator is not None:
                entry["has_perpetrator"] = has_perpetrator
            tag_rows.append(entry)
        if tag_rows:
            db.table("book_need_tags").insert(tag_rows).execute()
    except Exception:
        pass  # Tagging failed — book exists, tags can be filled in later

    return book


# ---------------------------------------------------------------------------
# Endpoint 1 — Log a read event
# ---------------------------------------------------------------------------

@app.post("/reads", status_code=201)
async def log_read(body: ReadEventRequest, user_id: str = Depends(get_current_user_id)):
    """Persist a new read event to the 'reads' table.

    User ID is derived from the verified JWT — never from the request body or URL.
    A Supabase database trigger (trg_new_read) fires after every insert and
    automatically recomputes the user's need_affinity scores and re-ranks
    their wishlist — so the recommendation engine updates immediately.
    """
    db = get_supabase()

    # Make sure the book is in our catalog
    book_check = db.table("books").select("id").eq("id", body.book_id).limit(1).execute()
    if not book_check.data:
        raise HTTPException(status_code=404, detail="Book not found")

    occurred_at = body.occurred_at or datetime.now(timezone.utc)

    payload = {
        "user_id": user_id,
        "book_id": body.book_id,
        "signal_type": body.signal_type,
        "pct_read": body.pct_read,
        "emotional_state": body.emotional_state,
        "occurred_at": occurred_at.isoformat(),
    }
    if body.post_emotional_state is not None:
        payload["post_emotional_state"] = body.post_emotional_state
    if body.review_text:
        payload["review_text"] = body.review_text

    result = db.table("reads").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to insert read event")

    return {"id": result.data[0]["id"], "status": "logged"}


# ---------------------------------------------------------------------------
# Endpoint 2 — Recommendations
# ---------------------------------------------------------------------------

@app.get("/recommendations", response_model=list[RecommendationResponse])
async def get_recommendations(limit: int = 10, user_id: str = Depends(get_current_user_id)):
    """Run the full four-stage scoring pipeline and return the top `limit` books.

    User ID is derived from the verified JWT.

    Steps:
      1. Pull all the user's read events (with need weights attached).
      2. Pull the user's current emotional state.
      3. Compute need affinities from all reads (scoring.py Stages 1+2).
      4. Modulate the affinity vector by current emotional state (Stage 3).
      5. Fetch up to 200 unread candidate books from the catalog.
      6. Score each candidate against the reader vector (Stage 4).
      7. For each of the top results, call Claude Haiku to generate why_text.
    """
    db = get_supabase()

    events = _fetch_user_read_events(db, user_id)
    state = _fetch_current_reading_state(db, user_id)

    now = datetime.now(timezone.utc)
    affinities = compute_all_affinities(events, now)
    reader_vector = modulate_for_state(affinities, state, now, events)

    read_book_ids = list({e.book_id for e in events})

    books_query = db.table("books").select("id, title, author, description, cover_url, ratings_count")
    if read_book_ids:
        books_query = books_query.not_.in_("id", read_book_ids)
    candidate_rows = books_query.limit(200).execute().data

    if not candidate_rows:
        return []

    candidate_ids = [b["id"] for b in candidate_rows]

    tag_rows = (
        db.table("book_need_tags")
        .select("book_id, need_id, weight")
        .in_("book_id", candidate_ids)
        .execute()
        .data
    )
    need_codes = db.table("needs").select("id, code").execute().data
    id_to_code = {n["id"]: n["code"] for n in need_codes}
    code_to_id = {n["code"]: n["id"] for n in need_codes}

    book_weights: dict[str, dict[str, float]] = {}
    for tag in tag_rows:
        bw = book_weights.setdefault(tag["book_id"], {})
        code = id_to_code.get(tag["need_id"])
        if code:
            bw[code] = float(tag["weight"])

    book_meta = {b["id"]: b for b in candidate_rows}
    profiles = [
        BookProfile(
            book_id=b["id"],
            need_weights=book_weights.get(b["id"], {}),
            ratings_count=int(b.get("ratings_count") or 0),
            recently_read_overlap=0.0,
        )
        for b in candidate_rows
    ]

    scored = [
        (profile, *match_score(reader_vector, profile))
        for profile in profiles
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:limit]

    results: list[RecommendationResponse] = []
    for profile, score, top_needs in top:
        meta = book_meta[profile.book_id]
        why = _generate_why_text(top_needs, meta["title"], meta.get("description") or "")
        top_need_ids = [code_to_id[n] for n in top_needs if n in code_to_id]
        results.append(
            RecommendationResponse(
                book_id=profile.book_id,
                title=meta["title"],
                author=meta.get("author"),
                cover_url=meta.get("cover_url"),
                match_score=score,
                top_need_ids=top_need_ids,
                why_text=why,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Endpoint 3 — Wishlist
# ---------------------------------------------------------------------------

@app.get("/wishlist", response_model=list[WishlistItemResponse])
async def get_wishlist(user_id: str = Depends(get_current_user_id)):
    """Return the user's saved wishlist books, sorted by their current match rank.

    User ID is derived from the verified JWT.
    The wishlist is maintained by the trg_new_read trigger and just read here.
    """
    db = get_supabase()

    rows = (
        db.table("wishlist")
        .select("book_id, match_score, rank, need_ids_matched, books(title, author, cover_url)")
        .eq("user_id", user_id)
        .order("rank", desc=False, nulls_first=False)
        .execute()
        .data
    )

    items: list[WishlistItemResponse] = []
    for r in rows:
        book = r.get("books") or {}
        items.append(
            WishlistItemResponse(
                book_id=r["book_id"],
                title=book.get("title", ""),
                author=book.get("author"),
                cover_url=book.get("cover_url"),
                match_score=float(r["match_score"]) if r["match_score"] is not None else None,
                rank=r.get("rank"),
                need_ids_matched=r.get("need_ids_matched"),
            )
        )

    return items
