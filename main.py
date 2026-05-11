"""
Folio — FastAPI application
Three endpoints that wrap the scoring engine and talk to Supabase.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import anthropic
from fastapi import FastAPI, HTTPException
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
# Supabase + Anthropic clients
# ---------------------------------------------------------------------------

_supabase: Optional[Client] = None
_anthropic: Optional[anthropic.Anthropic] = None


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _supabase = create_client(url, key)
    return _supabase


def get_anthropic() -> anthropic.Anthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Folio", version="0.1.0")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ReadEventRequest(BaseModel):
    book_id: str
    signal_type: str
    pct_read: float = 1.0
    emotional_state: int
    occurred_at: Optional[datetime] = None
    review_text: Optional[str] = None


class RecommendationResponse(BaseModel):
    book_id: str
    title: str
    author: Optional[str]
    cover_url: Optional[str]
    match_score: float
    top_need_ids: list[int]
    why_text: str


class WishlistItemResponse(BaseModel):
    book_id: str
    title: str
    author: Optional[str]
    cover_url: Optional[str]
    match_score: Optional[float]
    rank: Optional[int]
    need_ids_matched: Optional[list[int]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_user_read_events(db: Client, user_id: str) -> list[ReadEvent]:
    """Pull all read events for the user and hydrate book_need_weights."""
    rows = (
        db.table("reads")
        .select("book_id, signal_type, pct_read, emotional_state, occurred_at")
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

    # need_id (smallint) → need code
    need_codes = (
        db.table("needs")
        .select("id, code")
        .execute()
        .data
    )
    id_to_code = {n["id"]: n["code"] for n in need_codes}

    # book_id → {need_code: weight}
    book_weights: dict[str, dict[str, float]] = {}
    for tag in tag_rows:
        bw = book_weights.setdefault(tag["book_id"], {})
        code = id_to_code.get(tag["need_id"])
        if code:
            bw[code] = float(tag["weight"])

    events: list[ReadEvent] = []
    for r in rows:
        occurred = datetime.fromisoformat(r["occurred_at"])
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        events.append(
            ReadEvent(
                book_id=r["book_id"],
                signal_type=r["signal_type"],
                pct_read=float(r["pct_read"]),
                emotional_state=int(r["emotional_state"]),
                occurred_at=occurred,
                book_need_weights=book_weights.get(r["book_id"], {}),
            )
        )
    return events


def _fetch_current_reading_state(db: Client, user_id: str) -> ReadingState:
    """Return the user's current reading state, or a neutral fallback."""
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

    # active_need_ids stored as smallint[] → convert to need codes
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
    prompt = build_why_prompt(persona_label, top_needs, book_title, book_description)
    client = get_anthropic()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# Endpoint 1 — Log a read event
# ---------------------------------------------------------------------------

@app.post("/users/{user_id}/reads", status_code=201)
async def log_read(user_id: str, body: ReadEventRequest):
    """
    Persist a read event. The Supabase trigger (trg_new_read) automatically
    recomputes need_affinity and re-ranks the wishlist.
    """
    # Validate user exists
    db = get_supabase()
    user_check = db.table("users").select("id").eq("id", user_id).limit(1).execute()
    if not user_check.data:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate book exists
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
    if body.review_text:
        payload["review_text"] = body.review_text

    result = db.table("reads").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to insert read event")

    return {"id": result.data[0]["id"], "status": "logged"}


# ---------------------------------------------------------------------------
# Endpoint 2 — Recommendations
# ---------------------------------------------------------------------------

@app.get("/users/{user_id}/recommendations", response_model=list[RecommendationResponse])
async def get_recommendations(user_id: str, limit: int = 10):
    """
    Run the full scoring pipeline and return the top `limit` book recommendations.
    Why-text is generated via Claude Haiku.
    """
    db = get_supabase()

    # Check user
    user_check = db.table("users").select("id").eq("id", user_id).limit(1).execute()
    if not user_check.data:
        raise HTTPException(status_code=404, detail="User not found")

    # Pull read events + reading state
    events = _fetch_user_read_events(db, user_id)
    state = _fetch_current_reading_state(db, user_id)

    # Compute affinities + modulate
    now = datetime.now(timezone.utc)
    affinities = compute_all_affinities(events, now)
    reader_vector = modulate_for_state(affinities, state, now)

    # Exclude already-read book_ids
    read_book_ids = list({e.book_id for e in events})

    # Fetch candidate books (not yet read)
    books_query = db.table("books").select("id, title, author, description, cover_url, ratings_count")
    if read_book_ids:
        books_query = books_query.not_.in_("id", read_book_ids)
    candidate_rows = books_query.limit(200).execute().data

    if not candidate_rows:
        return []

    candidate_ids = [b["id"] for b in candidate_rows]

    # Fetch need tags for candidates
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

    # Build BookProfile list and score
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
        why = _generate_why_text(
            top_needs,
            meta["title"],
            meta.get("description") or "",
        )
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

@app.get("/users/{user_id}/wishlist", response_model=list[WishlistItemResponse])
async def get_wishlist(user_id: str):
    """Return the user's wishlist sorted by match_score (rank asc)."""
    db = get_supabase()

    user_check = db.table("users").select("id").eq("id", user_id).limit(1).execute()
    if not user_check.data:
        raise HTTPException(status_code=404, detail="User not found")

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
