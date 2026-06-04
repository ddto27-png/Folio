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

# The 13 psychological needs Folio tracks. Each book is tagged with how
# strongly it serves each need (0–1), and each reader builds an affinity
# profile across these same needs based on their reading history.
NEEDS = [
    "being_chosen",         # Unconditional love / being chosen by someone
    "surviving",            # Extreme resilience; making it through catastrophe
    "procedural_resolution",# The satisfaction of a mystery or system unravelling
    "moral_complexity",     # Sitting with ethical ambiguity; no easy answers
    "power_agency",         # Claiming autonomy in a system that denies it
    "wound_visible",        # Trauma named, witnessed, and validated
    "making_sense_history", # Understanding how the world got to where it is
    "self_remade",          # Transformation; second chances; reinvention
    "inside_power",         # Access to elite rooms, politics, strategy
    "identity_witnessed",   # Being truly seen in one's full specific identity
    "world_larger",         # Wonder, discovery, the sublime
    "creative_kinship",     # The bond between artists, makers, obsessives
    "anxiety_named",        # Contemporary dread articulated and companioned
]

# How fast old reads fade in influence. Half-life ≈ 139 days, meaning a read
# from 139 days ago counts for half as much as one from today.
DECAY_LAMBDA = 0.005

# Bayesian prior applied to books with very few public ratings.
# Keeps unknown books from scoring artificially high or low.
# Anchored at 0.2 so sparse books are always pulled *down*, never up.
COLD_BOOK_PRIOR = 0.2
COLD_BOOK_THRESHOLD = 50  # number of ratings at which we trust the score fully

# How much we penalise a book that's too similar to something the reader
# just finished (discourages recommending the same kind of book back-to-back).
NOVELTY_DISCOUNT = 0.15

# Multipliers applied to needs based on the reader's current emotional state.
# State 1 = in crisis → amplify wound_visible, anxiety_named, surviving.
# State 5 = thriving → amplify being_chosen, identity_witnessed, creative_kinship.
STATE_BOOSTS: dict[int, dict[str, float]] = {
    1: {"wound_visible": 2.0, "anxiety_named": 1.4, "surviving": 1.4},
    2: {"wound_visible": 1.4, "being_chosen": 1.4},
    3: {"making_sense_history": 1.4, "moral_complexity": 1.4, "creative_kinship": 1.4},
    4: {"world_larger": 1.4, "power_agency": 1.4, "inside_power": 1.4, "self_remade": 1.4},
    5: {"being_chosen": 1.4, "identity_witnessed": 1.4, "creative_kinship": 1.4},
}

# How much each reader action (signal) means. Positive = liked it,
# negative = didn't. Re-reading is the strongest positive signal.
SIGNAL_WEIGHTS = {
    "star_5":         1.0,   # loved it
    "star_4":         0.6,   # really liked it
    "star_3":         0.1,   # it was okay
    "star_2":        -0.4,   # didn't like it
    "star_1":        -0.8,   # disliked it
    "abandoned":     -0.5,   # gave up on it
    "re_read":        0.9,   # read it again — very strong signal
    "highlighted":    0.3,   # marked passages
    "added_wishlist": 0.2,   # saved for later
    "shared":         0.25,  # recommended to someone else
    "clicked_rec":    0.1,   # showed interest in a recommendation
    "ignored_rec":   -0.05,  # skipped past a recommendation
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

# Represents one logged reading event by a user.
@dataclass
class ReadEvent:
    book_id: str
    signal_type: str            # key in SIGNAL_WEIGHTS (e.g. "star_5", "abandoned")
    pct_read: float             # 0.0–1.0, how much of the book was read
    emotional_state: int        # 1 (crisis) – 5 (joyful) when the book was read
    occurred_at: datetime
    book_need_weights: dict[str, float]   # need → 0–1 weight pulled from book_need_tags


# Stores the computed affinity score for one reader × one need.
# Persisted to the need_affinity table and refreshed after each read.
@dataclass
class NeedAffinity:
    need: str
    base_score: float = 0.0      # stable long-term score across all reads
    decayed_score: float = 0.0   # recency-weighted score (recent reads count more)
    volatility: float = 0.0      # how inconsistently the reader signals this need
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Captures the reader's emotional state at a point in time.
# Used to boost certain needs in the recommendation pipeline.
@dataclass
class ReadingState:
    emotional_state: int           # 1–5
    active_need_ids: list[str] = field(default_factory=list)  # explicitly requested needs
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_current: bool = True

    def is_stale(self, now: Optional[datetime] = None) -> bool:
        """Returns True if the state was captured more than 48 hours ago.
        Stale states are ignored so old moods don't skew recommendations."""
        now = now or datetime.now(timezone.utc)
        age_hours = (now - self.captured_at).total_seconds() / 3600
        return age_hours > 48


# A book's psychological profile — the need weights assigned by Claude Haiku
# during ingestion, plus metadata used by the scoring engine.
@dataclass
class BookProfile:
    book_id: str
    need_weights: dict[str, float]   # need → 0–1, how strongly the book serves each need
    ratings_count: int               # total public ratings (for cold-book adjustment)
    recently_read_overlap: float = 0.0   # 0–1, similarity to books already read recently


# ---------------------------------------------------------------------------
# Stage 1 — Signal contribution
# ---------------------------------------------------------------------------

def finish_multiplier(pct_read: float) -> float:
    """Scales the credibility of a signal by how much of the book was actually read.
    A 1-star rating from someone who read 10% carries less weight than one from
    someone who finished the whole book."""
    if pct_read >= 0.9:
        return 1.0   # finished — full credibility
    elif pct_read >= 0.5:
        return 0.6   # got through most of it
    else:
        return 0.3   # barely started


def emotional_alignment(emotional_state: int, need: str) -> float:
    """Amplifies a signal when the reader's emotional state aligns with the need.
    Example: someone in crisis (state 1) reading a 'wound_visible' book is a
    much stronger signal for that need than someone happy reading the same book.
    Returns a multiplier in the range [0.7, 1.3]."""
    boosts = STATE_BOOSTS.get(emotional_state, {})
    return boosts.get(need, 1.0) * 0.3 + 0.7   # scale boost into [0.7, 1.3]


def signal_contribution(event: ReadEvent, need: str) -> float:
    """Stage 1: raw contribution of a single read event to a need's affinity.

    Multiplies four factors together:
      - signal_weight:       how positive/negative the rating is (SIGNAL_WEIGHTS)
      - book_need_weight:    how strongly this book tags this need (0–1)
      - finish_multiplier:   credibility based on how much was read
      - emotional_alignment: amplify if mood matched the need at time of reading
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
    """Returns how many days ago this event occurred. Used for decay calculation."""
    delta = now - event.occurred_at
    return delta.total_seconds() / 86_400


def compute_affinity(
    events: list[ReadEvent],
    need: str,
    now: Optional[datetime] = None,
) -> NeedAffinity:
    """Stage 2: aggregate all read events into a stable affinity score for one need.

    Produces three values and blends them:
      - base_score:    raw sum with diminishing returns (read_count ^ 0.6) — stable
      - decayed_score: exponentially weighted by recency (half-life ~139 days) — recent
      - volatility:    std_dev / mean of last 12 contributions — how inconsistent signals are

    Blending formula:
      alpha = 0.3 + 0.4 × volatility
      affinity = alpha × decayed + (1 - alpha) × base

    High volatility (reader sends mixed signals for this need) → lean on recent reads.
    Low volatility (reader consistently likes/dislikes this need) → lean on long-term base.
    """
    now = now or datetime.now(timezone.utc)

    contributions = [signal_contribution(e, need) for e in events]

    if not contributions:
        return NeedAffinity(need=need)

    # Base score: sum all contributions, but penalise having too many reads
    # (read_count ^ 0.6 grows slower than linear, giving diminishing returns).
    raw_sum = sum(contributions)
    read_count = len(contributions)
    base_raw = raw_sum / (read_count ** 0.6)
    base_score = max(0.0, min(1.0, base_raw))

    # Decayed score: weight each contribution by how recently it happened.
    # Older reads shrink exponentially; very recent reads dominate.
    decayed_raw = sum(
        c * math.exp(-DECAY_LAMBDA * days_since(e, now))
        for c, e in zip(contributions, events)
    )
    decayed_score = max(0.0, min(1.0, decayed_raw / (read_count ** 0.6)))

    # Volatility: how consistent the last 12 signals are (std_dev / mean).
    # High volatility = reader's feelings about this need are erratic.
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

    # Blend: high volatility → trust recent reads more (higher alpha).
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
    """Runs compute_affinity for all 13 needs at once.
    Returns a dict mapping need_code → NeedAffinity."""
    return {need: compute_affinity(events, need, now) for need in NEEDS}


def affinity_score(na: NeedAffinity) -> float:
    """Extracts the final blended score from a NeedAffinity object.
    Used in modulate_for_state to build the reader vector."""
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
    """Stage 3: boost needs that match the reader's current emotional state.

    Two boost sources:
      - active_need_ids: needs the reader explicitly said they want (2× boost)
      - STATE_BOOSTS:    needs that naturally align with the emotional state (up to 2× boost)

    If the state is stale (captured >48h ago), no modulation is applied —
    we fall back to the raw affinity profile.

    The result is normalised so all values sum to 1.0, making it a proper
    probability-like vector that can be dot-producted against book need weights.
    """
    now = now or datetime.now(timezone.utc)

    # Don't apply mood boosts if the emotional state is from yesterday or earlier
    if state.is_stale(now):
        boosts = {}
    else:
        boosts = STATE_BOOSTS.get(state.emotional_state, {})

    modulated: dict[str, float] = {}
    for need in NEEDS:
        base = affinity_score(affinities.get(need, NeedAffinity(need=need)))

        if need in state.active_need_ids:
            boost = 2.0           # reader explicitly requested this need
        elif need in boosts:
            boost = boosts[need]  # need aligns with the reader's current mood
        else:
            boost = 1.0           # no boost

        modulated[need] = base * boost

    # Normalise: divide every value by the total so they sum to 1.0
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
    """Stage 4: score a single book against the reader's modulated need vector.

    Returns (score 0–1, top_needs) where top_needs drives the 'why this book' text.

    Three steps:
      1. Dot product: multiply reader affinity × book need weight for each need, sum it.
         High score = book's needs align well with what the reader is drawn to.
      2. Bayesian cold-book adjustment: if the book has fewer than 50 public ratings,
         pull the score toward a safe prior (0.2) so unknown books aren't over-ranked.
      3. Novelty discount: if the book is too similar to something the reader just
         finished, reduce the score slightly to promote variety.
    """
    # Step 1: dot product of reader profile × book profile across all 13 needs
    raw = sum(
        reader_vector.get(need, 0.0) * book.need_weights.get(need, 0.0)
        for need in NEEDS
    )

    # Step 2: Bayesian regularisation — scale confidence by how many ratings the book has.
    # A book with 5 ratings gets mostly the prior; one with 500 gets the raw score.
    confidence = min(1.0, book.ratings_count / COLD_BOOK_THRESHOLD)
    bayesian = confidence * raw + (1 - confidence) * COLD_BOOK_PRIOR

    # Step 3: novelty discount — reduce score if book overlaps too much with recent reads
    novelty = 1.0 - NOVELTY_DISCOUNT * book.recently_read_overlap
    final = bayesian * novelty

    # Find the top 2 needs driving the match — these get passed to the why_text generator
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
    """Score every candidate book and return them sorted by match score (highest first).
    Each item in the result is (book, score, top_needs)."""
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
    """Builds the prompt sent to Claude Haiku to generate the personalised
    'why this book' blurb shown on each recommendation card.

    The result should sound like a knowledgeable friend explaining the match,
    not an algorithm. Lead with the psychological need, not the genre or plot.
    Cache the result — only regenerate when top_needs changes for this reader × book pair.
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
    """Run all four stages end-to-end in one call.

    Takes the reader's full history + current state + a list of unread books,
    and returns them ranked by how well they match right now.
    Result: list of (book, match_score, top_needs) sorted descending by score.
    """
    now = now or datetime.now(timezone.utc)

    affinities      = compute_all_affinities(events, now)         # Stages 1 + 2
    reader_vector   = modulate_for_state(affinities, state, now)  # Stage 3
    ranked          = rank_books(reader_vector, candidate_books)   # Stage 4

    return ranked
