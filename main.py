"""
Folio — FastAPI application
Three endpoints that wrap the scoring engine and talk to Supabase.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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
# Book tagging helpers (used by find-or-create endpoint)
# ---------------------------------------------------------------------------

NEED_CODE_TO_ID: dict[str, int] = {
    "being_chosen": 1, "surviving": 2, "procedural_resolution": 3,
    "moral_complexity": 4, "power_agency": 5, "wound_visible": 6,
    "making_sense_history": 7, "self_remade": 8, "inside_power": 9,
    "identity_witnessed": 10, "world_larger": 11, "creative_kinship": 12,
    "anxiety_named": 13,
}

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

_TAGGING_SYSTEM = (
    "You are a literary psychologist. Given a book's title, author, and description, "
    "assign weights (0.0-1.0) reflecting how strongly it serves each of 13 psychological needs. "
    "Most books serve 2-4 needs strongly (>=0.4); the rest should be 0.0-0.2. "
    "For wound_visible also set has_perpetrator: true if the wound was caused by another person. "
    "Respond with valid JSON only - no explanation, no markdown fences."
)

_TAGGING_TEMPLATE = """Book: "{title}" by {author}
Description: {description}

Score across these 13 needs (0.0-1.0 each):
{needs_list}

Return JSON: {{"being_chosen":0.0,"surviving":0.0,"procedural_resolution":0.0,"moral_complexity":0.0,"power_agency":0.0,"wound_visible":0.0,"making_sense_history":0.0,"self_remade":0.0,"inside_power":0.0,"identity_witnessed":0.0,"world_larger":0.0,"creative_kinship":0.0,"anxiety_named":0.0,"has_perpetrator":false}}"""


def _tag_book(client: anthropic.Anthropic, title: str, author: str, description: str) -> dict:
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
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _ol_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Folio/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read())


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


class BookSearchResult(BaseModel):
    id: Optional[str]
    title: str
    author: Optional[str]
    cover_url: Optional[str]
    pub_year: Optional[int]
    in_catalog: bool
    ol_key: Optional[str]


class FindOrCreateBookRequest(BaseModel):
    title: str
    author: Optional[str] = None
    cover_url: Optional[str] = None
    pub_year: Optional[int] = None
    ol_key: Optional[str] = None


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

    # need_id (smallint) -> need code
    need_codes = (
        db.table("needs")
        .select("id, code")
        .execute()
        .data
    )
    id_to_code = {n["id"]: n["code"] for n in need_codes}

    # book_id -> {need_code: weight}
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

    # active_need_ids stored as smallint[] -> convert to need codes
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
# Endpoint: Book search (catalog + Open Library)
# ---------------------------------------------------------------------------

@app.get("/books/search", response_model=list[BookSearchResult])
async def search_books(q: str, limit: int = 8):
    if len(q.strip()) < 2:
        return []

    db = get_supabase()

    # Search our catalog first
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

    # Fill remaining slots from Open Library
    remaining = limit - len(results)
    if remaining > 0:
        try:
            qs = urllib.parse.urlencode({
                "q": q, "limit": remaining + 5,
                "fields": "key,title,author_name,cover_i,first_publish_year",
            })
            data = _ol_get(f"https://openlibrary.org/search.json?{qs}")
            for doc in data.get("docs", []):
                title = doc.get("title", "")
                if title.lower() in catalog_titles:
                    continue
                authors = doc.get("author_name", [])
                cover_i = doc.get("cover_i")
                results.append({
                    "id": None,
                    "title": title,
                    "author": ", ".join(authors[:2]) if authors else None,
                    "cover_url": f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None,
                    "pub_year": doc.get("first_publish_year"),
                    "in_catalog": False,
                    "ol_key": doc.get("key"),
                })
                catalog_titles.add(title.lower())
                if len(results) >= limit:
                    break
        except Exception:
            pass

    return results[:limit]


# ---------------------------------------------------------------------------
# Endpoint: Find or create a book (adds to catalog + tags via Claude)
# ---------------------------------------------------------------------------

@app.post("/books/find-or-create")
async def find_or_create_book(body: FindOrCreateBookRequest):
    db = get_supabase()

    # Return existing book if already in catalog
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

    # Fetch description from Open Library if we have a work key
    description: Optional[str] = None
    if body.ol_key:
        try:
            work = _ol_get(f"https://openlibrary.org{body.ol_key}.json")
            raw = work.get("description")
            description = raw.get("value") if isinstance(raw, dict) else raw
        except Exception:
            pass

    # Insert book
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

    # Tag with Claude Haiku (synchronous - needed for scoring to work immediately)
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
                continue
            entry = {"book_id": book_id, "need_id": need_id, "weight": w, "source": "llm"}
            if code == "wound_visible" and has_perpetrator is not None:
                entry["has_perpetrator"] = has_perpetrator
            tag_rows.append(entry)
        if tag_rows:
            db.table("book_need_tags").insert(tag_rows).execute()
    except Exception:
        pass  # Book exists; tags can be added later

    return book


# ---------------------------------------------------------------------------
# Endpoint 1 - Log a read event
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
# Endpoint 2 - Recommendations
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
# Endpoint 3 - Wishlist
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
