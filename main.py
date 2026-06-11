"""
Folio — FastAPI backend
=======================
Five endpoints that connect the scoring engine (scoring.py) to the Supabase database
and expose an HTTP API the Next.js frontend consumes.

Endpoints:
  GET  /books/search              — search catalog + Open Library live
  POST /books/request             — request a book be added to the catalog (nightly batch)
  POST /reads                     — log a read event (JWT-authenticated)
  GET  /recommendations           — run full scoring pipeline and return top books (JWT-authenticated)
  GET  /wishlist                  — return user's saved books ranked by match score (JWT-authenticated)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import anthropic
import jwt as pyjwt
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
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
# App
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

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


class ReadingStateRequest(BaseModel):
    """Body for POST /reading-state — the user's current emotional state and explicit need interests."""
    emotional_state: int = Field(ge=1, le=5)
    active_need_ids: list[int] = []


class BookSearchResult(BaseModel):
    """One result from GET /books/search — catalog only."""
    id: str
    title: str
    author: Optional[str]
    cover_url: Optional[str]
    pub_year: Optional[int]
    in_catalog: bool = True


class BookRequestBody(BaseModel):
    """Body for POST /books/request — a title the user wants added to the catalog."""
    title: str
    author: Optional[str] = None


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
    """Search for books by title within the Folio catalog.

    Returns only books already in our catalog — these have need tags and can
    be logged immediately. No external API calls are made at request time.
    If the user's book isn't found, the frontend shows a 'Request this book'
    button which calls POST /books/request.
    """
    if len(q.strip()) < 2:
        return []

    db = get_supabase()
    catalog = (
        db.table("books")
        .select("id, title, author, cover_url, pub_year")
        .ilike("title", f"%{q}%")
        .limit(limit)
        .execute()
        .data
    )
    return [{**r, "in_catalog": True} for r in catalog]


# ---------------------------------------------------------------------------
# Endpoint: Find or create a book (adds to catalog + tags via Claude)
# ---------------------------------------------------------------------------

@app.post("/books/request", status_code=202)
async def request_book(
    body: BookRequestBody,
    user_id: str = Depends(get_current_user_id),
):
    """Record a user's request to add a book to the catalog.

    Does not perform any tagging or external API calls at request time.
    The nightly_ingest.py job processes pending requests in batch.

    Returns 202 Accepted immediately — the book will appear in the catalog
    within 24 hours once the nightly job runs.
    """
    db = get_supabase()
    db.rpc("upsert_book_request", {"p_title": body.title, "p_author": body.author or ""}).execute()
    return {"status": "requested", "message": "We'll add this book within 24 hours."}


# ---------------------------------------------------------------------------
# Endpoint 0 — Update reading state (emotional state + active needs)
# ---------------------------------------------------------------------------

@app.post("/reading-state", status_code=200)
async def update_reading_state(body: ReadingStateRequest, user_id: str = Depends(get_current_user_id)):
    """Save the user's current emotional state and explicitly chosen needs.

    Marks any previous current row as not current, then inserts a fresh one.
    The recommendations engine picks this up immediately on the next GET /recommendations call:
    - emotional_state feeds the mirror/escape modulation in stage 3
    - active_need_ids each receive a 2× boost in stage 3 regardless of reading history
    """
    db = get_supabase()
    db.table("reading_state") \
      .update({"is_current": False}) \
      .eq("user_id", user_id) \
      .eq("is_current", True) \
      .execute()
    db.table("reading_state").insert({
        "user_id": user_id,
        "emotional_state": body.emotional_state,
        "active_need_ids": body.active_need_ids,
        "is_current": True,
    }).execute()
    return {"ok": True}


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
