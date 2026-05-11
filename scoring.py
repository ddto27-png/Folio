"""
Folio — Psychological Need Scoring Engine
==========================================
Four-stage pipeline:
  1. signal_contribution()   — raw weight from a single read event
  2. compute_affinity()      — aggregate into per-need affinity score
  3. modulate_for_state()    — amplify needs matching current emotional state
  4. match_score()           — score a book against a reader's modulated profile
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEEDS = [
    "being_chosen",
    "surviving",
    "procedural_resolution",
    "moral_complexity",
    "power_agency",
    "wound_visible",
    "making_sense_history",
    "self_remade",
    "inside_power",
    "identity_witnessed",
    "world_larger",
    "creative_kinship",
    "anxiety_named",
]

# Decay constant: half-life ≈ 139 days
DECAY_LAMBDA = 0.005

# Bayesian prior for books with few ratings.
# Anchored at 0.2 (below typical raw dot-product scores of 0.3–0.7) so cold
# books are always pulled *down* toward the prior, never pushed up.
COLD_BOOK_PRIOR = 0.2
COLD_BOOK_THRESHOLD = 50  # ratings needed for full confidence

# Novelty penalty for books too similar to recent reads
NOVELTY_DISCOUNT = 0.15

# State→need alignment boosts
STATE_BOOSTS: dict[int, dict[str, float]] = {
    1: {"wound_visible": 2.0, "anxiety_named": 1.4, "surviving": 1.4},
    2: {"wound_visible": 1.4, "being_chosen": 1.4},
    3: {"making_sense_history": 1.4, "moral_complexity": 1.4, "creative_kinship": 1.4},
    4: {"world_larger": 1.4, "power_agency": 1.4, "inside_power": 1.4, "self_remade": 1.4},
    5: {"being_chosen": 1.4, "identity_witnessed": 1.4, "creative_kinship": 1.4},
}

SIGNAL_WEIGHTS = {
    "star_5":         1.0,
    "star_4":         0.6,
    "star_3":         0.1,
    "star_2":        -0.4,
    "star_1":        -0.8,
    "abandoned":     -0.5,
    "re_read":        0.9,
    "highlighted":    0.3,
    "added_wishlist": 0.2,
    "shared":         0.25,
    "clicked_rec":    0.1,
    "ignored_rec":   -0.05,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ReadEvent:
    book_id: str
    signal_type: str            # key in SIGNAL_WEIGHTS
    pct_read: float             # 0.0 – 1.0
    emotional_state: int        # 1 (crisis) – 5 (joyful)
    occurred_at: datetime
    book_need_weights: dict[str, float]   # need → 0–1 weight from book_need_tags


@dataclass
class NeedAffinity:
    need: str
    base_score: float = 0.0
    decayed_score: float = 0.0
    volatility: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ReadingState:
    emotional_state: int           # 1–5
    active_need_ids: list[str] = field(default_factory=list)
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_current: bool = True

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        age_hours = (now - self.captured_at).total_seconds() / 3600
        return age_hours > 48


@dataclass
class BookProfile:
    book_id: str
    need_weights: dict[str, float]   # need → 0–1
    ratings_count: int
    recently_read_overlap: float = 0.0   # 0–1, similarity to recent reads


# ---------------------------------------------------------------------------
# Stage 1 — Signal contribution
# ---------------------------------------------------------------------------

def finish_multiplier(pct_read: float) -> float:
    """How much credibility to give the signal based on how much was read."""
    if pct_read >= 0.9:
        return 1.0
    elif pct_read >= 0.5:
        return 0.6
    else:
        return 0.3


def emotional_alignment(emotional_state: int, need: str) -> float:
    """
    Amplify signal when the reader's state aligns with what the need addresses.
    A grief-read of 'wound_visible' in state 1 is a strong signal.
    The same book read in state 5 (joyful) is weaker evidence of that need.
    """
    boosts = STATE_BOOSTS.get(emotional_state, {})
    return boosts.get(need, 1.0) * 0.3 + 0.7   # scale boost → [0.7, 1.3]


def signal_contribution(event: ReadEvent, need: str) -> float:
    """
    Stage 1: raw contribution of a single read event to a need's affinity.

    contribution = signal_weight
                 × book_need_weight
                 × finish_multiplier
                 × emotional_alignment
    """
    sig_w   = SIGNAL_WEIGHTS.get(event.signal_type, 0.0)
    need_w  = event.book_need_weights.get(need, 0.0)
    finish  = finish_multiplier(event.pct_read)
    align   = emotional_alignment(event.emotional_state, need)

    return sig_w * need_w * finish * align


# ---------------------------------------------------------------------------
# Stage 2 — Affinity scoring
# ---------------------------------------------------------------------------

def days_since(event: ReadEvent, now: datetime) -> float:
    delta = now - event.occurred_at
    return delta.total_seconds() / 86_400


def compute_affinity(
    events: list[ReadEvent],
    need: str,
    now: Optional[datetime] = None,
) -> NeedAffinity:
    """
    Stage 2: aggregate all read events into a stable affinity score.

    - base_score:    raw sum with diminishing returns (read_count ^ 0.6)
    - decayed_score: exponentially weighted by recency (half-life ~139 days)
    - volatility:    std_dev / mean of last 12 contributions
    - final affinity: α × decayed + (1-α) × base
                      where α = 0.3 + 0.4 × volatility
                      (volatile needs lean on recency; stable needs lean on base)
    """
    now = now or datetime.now(timezone.utc)

    contributions = [signal_contribution(e, need) for e in events]

    if not contributions:
        return NeedAffinity(need=need)

    # Base score — diminishing returns across many reads
    raw_sum = sum(contributions)
    read_count = len(contributions)
    base_raw = raw_sum / (read_count ** 0.6)
    base_score = max(0.0, min(1.0, base_raw))

    # Recency-decayed score
    decayed_raw = sum(
        c * math.exp(-DECAY_LAMBDA * days_since(e, now))
        for c, e in zip(contributions, events)
    )
    decayed_score = max(0.0, min(1.0, decayed_raw / (read_count ** 0.6)))

    # Volatility from last 12 events
    recent = contributions[-12:]
    if len(recent) >= 2:
        mean_c = sum(recent) / len(recent)
        if mean_c != 0:
            variance = sum((c - mean_c) ** 2 for c in recent) / len(recent)
            volatility = math.sqrt(variance) / abs(mean_c)
            volatility = min(1.0, volatility)
        else:
            volatility = 0.0
    else:
        volatility = 0.0

    # Blend
    alpha = 0.3 + 0.4 * volatility
    affinity_score = alpha * decayed_score + (1 - alpha) * base_score

    return NeedAffinity(
        need=need,
        base_score=round(base_score, 4),
        decayed_score=round(decayed_score, 4),
        volatility=round(volatility, 4),
        last_updated=now,
    )


def compute_all_affinities(
    events: list[ReadEvent],
    now: Optional[datetime] = None,
) -> dict[str, NeedAffinity]:
    """Compute affinity for all 13 needs at once."""
    return {need: compute_affinity(events, need, now) for need in NEEDS}


def affinity_score(na: NeedAffinity) -> float:
    """Final blended affinity value from a NeedAffinity object."""
    alpha = 0.3 + 0.4 * na.volatility
    return alpha * na.decayed_score + (1 - alpha) * na.base_score


# ---------------------------------------------------------------------------
# Stage 3 — State modulation
# ---------------------------------------------------------------------------

def modulate_for_state(
    affinities: dict[str, NeedAffinity],
    state: ReadingState,
    now: Optional[datetime] = None,
) -> dict[str, float]:
    """
    Stage 3: amplify needs that match the reader's current emotional state.

    If state is stale (>48h), fall back to neutral (no boost).
    Returns a normalised vector that sums to 1.0.
    """
    now = now or datetime.now(timezone.utc)

    # Stale state → no modulation
    if state.is_stale(now):
        boosts = {}
    else:
        boosts = STATE_BOOSTS.get(state.emotional_state, {})

    modulated: dict[str, float] = {}
    for need in NEEDS:
        base = affinity_score(affinities.get(need, NeedAffinity(need=need)))

        if need in state.active_need_ids:
            boost = 2.0                         # explicit: user said they need this
        elif need in boosts:
            boost = boosts[need]                # implicit state alignment
        else:
            boost = 1.0

        modulated[need] = base * boost

    # Normalise to sum to 1.0
    total = sum(modulated.values())
    if total > 0:
        modulated = {n: v / total for n, v in modulated.items()}

    return modulated


# ---------------------------------------------------------------------------
# Stage 4 — Match scoring
# ---------------------------------------------------------------------------

def match_score(
    reader_vector: dict[str, float],
    book: BookProfile,
) -> tuple[float, list[str]]:
    """
    Stage 4: score a single book against the reader's modulated need vector.

    Returns (score 0–1, top_needs list for why_text generation).

    Steps:
      1. Dot product of reader × book need vectors
      2. Bayesian adjustment for cold books (<50 ratings)
      3. Novelty discount for books similar to recent reads
    """
    # 1. Dot product
    raw = sum(
        reader_vector.get(need, 0.0) * book.need_weights.get(need, 0.0)
        for need in NEEDS
    )

    # 2. Bayesian cold-book regularisation
    confidence = min(1.0, book.ratings_count / COLD_BOOK_THRESHOLD)
    bayesian = confidence * raw + (1 - confidence) * COLD_BOOK_PRIOR

    # 3. Novelty discount
    novelty = 1.0 - NOVELTY_DISCOUNT * book.recently_read_overlap
    final = bayesian * novelty

    # Top 2 contributing needs → drive why_text
    contributions = {
        need: reader_vector.get(need, 0.0) * book.need_weights.get(need, 0.0)
        for need in NEEDS
    }
    top_needs = sorted(contributions, key=contributions.get, reverse=True)[:2]

    return round(final, 4), top_needs


def rank_books(
    reader_vector: dict[str, float],
    books: list[BookProfile],
) -> list[tuple[BookProfile, float, list[str]]]:
    """
    Score and rank a list of books for a reader.
    Returns list of (book, score, top_needs) sorted descending.
    """
    scored = [
        (book, *match_score(reader_vector, book))
        for book in books
    ]
    return sorted(scored, key=lambda x: x[1], reverse=True)


# ---------------------------------------------------------------------------
# Why-text prompt (pass to your LLM of choice)
# ---------------------------------------------------------------------------

def build_why_prompt(
    persona_label: str,
    top_needs: list[str],
    book_title: str,
    book_description: str,
) -> str:
    """
    Build the prompt for generating a personalised 'why this book' explanation.
    Call this with your LLM (Claude, GPT-4, etc.) and cache the result.
    Only regenerate when top_needs changes for this reader × book pair.
    """
    needs_str = " and ".join(f'"{n.replace("_", " ")}"' for n in top_needs)
    return f"""You are explaining why a specific book matches a reader's deep psychological needs.

Reader persona: {persona_label}
Reader's top active needs right now: {needs_str}

Book: "{book_title}"
Book description: {book_description}

Write 2 sentences (max 40 words total) explaining why this book will resonate with this reader.
- Lead with the specific need it serves, not the genre or plot
- Sound like a knowledgeable friend, not an algorithm
- Do not mention the reader's persona label directly
- Do not use the phrase "based on your preferences"
"""


# ---------------------------------------------------------------------------
# Full pipeline — convenience wrapper
# ---------------------------------------------------------------------------

def full_pipeline(
    events: list[ReadEvent],
    state: ReadingState,
    candidate_books: list[BookProfile],
    now: Optional[datetime] = None,
) -> list[tuple[BookProfile, float, list[str]]]:
    """
    Run all four stages end-to-end.

    Returns ranked list of (book, match_score, top_needs).
    """
    now = now or datetime.now(timezone.utc)

    affinities      = compute_all_affinities(events, now)         # Stage 1+2
    reader_vector   = modulate_for_state(affinities, state, now)  # Stage 3
    ranked          = rank_books(reader_vector, candidate_books)   # Stage 4

    return ranked
