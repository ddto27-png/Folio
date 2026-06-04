"""
Folio — Psychological Need Scoring Engine
==========================================
Four-stage pipeline:
  1. signal_contribution()   — raw weight from a single read event
  2. compute_affinity()      — aggregate into per-need affinity score
  3. modulate_for_state()    — amplify needs based on emotional state + learned reading style
  4. match_score()           — score a book against a reader's modulated profile

Key change from v1:
  modulate_for_state() now learns whether each reader uses books as a mirror
  (deepening their current emotional state) or as an escape (shifting it).
  It does this by comparing pre- and post-reading emotional states across past reads.
  Until a reader has ≥3 before/after pairs in their current emotional zone, the engine
  falls back to population-level mirror boosts (the original behaviour).
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The 13 psychological needs Folio tracks. Each book is tagged with how
# strongly it serves each need (0–1), and each reader builds an affinity
# profile across these same needs based on their reading history.
NEEDS = [
    "being_chosen",          # Unconditional love / being chosen by someone
    "surviving",             # Extreme resilience; making it through catastrophe
    "procedural_resolution", # The satisfaction of a mystery or system unravelling
    "moral_complexity",      # Sitting with ethical ambiguity; no easy answers
    "power_agency",          # Claiming autonomy in a system that denies it
    "wound_visible",         # Trauma named, witnessed, and validated
    "making_sense_history",  # Understanding how the world got to where it is
    "self_remade",           # Transformation; second chances; reinvention
    "inside_power",          # Access to elite rooms, politics, strategy
    "identity_witnessed",    # Being truly seen in one's full specific identity
    "world_larger",          # Wonder, discovery, the sublime
    "creative_kinship",      # The bond between artists, makers, obsessives
    "anxiety_named",         # Contemporary dread articulated and companioned
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

# ---------------------------------------------------------------------------
# Mirror boosts — for readers who use books to validate/deepen current state.
# Applied when: (a) the reader is a confirmed mirror reader, or
#               (b) we don't yet have enough before/after data to decide.
# "Sad reader → wound_visible book" is the population-level default.
# ---------------------------------------------------------------------------
MIRROR_BOOSTS: dict[int, dict[str, float]] = {
    1: {"wound_visible": 2.0, "anxiety_named": 1.4, "surviving": 1.4},
    2: {"wound_visible": 1.4, "being_chosen": 1.4},
    3: {"making_sense_history": 1.4, "moral_complexity": 1.4, "creative_kinship": 1.4},
    4: {"world_larger": 1.4, "power_agency": 1.4, "inside_power": 1.4, "self_remade": 1.4},
    5: {"being_chosen": 1.4, "identity_witnessed": 1.4, "creative_kinship": 1.4},
}

# ---------------------------------------------------------------------------
# Escape boosts — for readers who use books to shift their emotional state.
# Applied when before/after data shows this reader's mood consistently moves
# in a positive direction after reading (post_state > pre_state on average).
# "Sad reader → self_remade book" is the escape-reader default.
# ---------------------------------------------------------------------------
ESCAPE_BOOSTS: dict[int, dict[str, float]] = {
    1: {"self_remade": 1.8, "world_larger": 1.6, "being_chosen": 1.4},
    2: {"self_remade": 1.6, "world_larger": 1.4, "being_chosen": 1.3},
    3: {"world_larger": 1.4, "power_agency": 1.4, "procedural_resolution": 1.3},
    4: {"moral_complexity": 1.4, "procedural_resolution": 1.4, "inside_power": 1.3},
    5: {"procedural_resolution": 1.4, "moral_complexity": 1.3, "creative_kinship": 1.2},
}

# Alias kept for backward compatibility — used in emotional_alignment() where
# we want the static population-level behaviour (not personalised).
STATE_BOOSTS = MIRROR_BOOSTS

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
    emotional_state: int        # 1–5: how the reader felt BEFORE reading
    occurred_at: datetime
    book_need_weights: dict[str, float]   # need → 0–1 weight pulled from book_need_tags
    post_emotional_state: Optional[int] = None  # 1–5: how the reader felt AFTER reading
                                                 # None if not captured (optional field)


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
    """Amplifies a signal when the reader's pre-reading emotional state aligns with the need.
    Uses the static MIRROR_BOOSTS (population-level) — this is intentional.
    signal_contribution() is about measuring what a book contributed to a need,
    not about personalising recommendations. Personalisation happens in modulate_for_state().
    Returns a multiplier in the range [0.7, 1.3]."""
    boosts = STATE_BOOSTS.get(emotional_state, {})
    return boosts.get(need, 1.0) * 0.3 + 0.7   # scale boost into [0.7, 1.3]


def signal_contribution(event: ReadEvent, need: str) -> float:
    """Stage 1: raw contribution of a single read event to a need's affinity.

    Multiplies four factors together:
      - signal_weight:       how positive/negative the rating is (SIGNAL_WEIGHTS)
      - book_need_weight:    how strongly this book tags this need (0–1)
      - finish_multiplier:   credibility based on how much was read
      - emotional_alignment: amplify if pre-reading mood matched the need
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
# Personal reading style — learned from before/after emotional data
# ---------------------------------------------------------------------------

def _state_zone(state: int) -> str:
    """Bucket 1–5 emotional states into three zones.
    Used to group before/after pairs for style learning — we want to know
    how a reader's mood shifts when they're in a low, neutral, or high state,
    not for every specific value on the scale."""
    if state <= 2:
        return 'low'
    if state == 3:
        return 'neutral'
    return 'high'


def compute_personal_style(
    events: list[ReadEvent],
    current_state: int,
    min_events: int = 3,
) -> Optional[float]:
    """Compute a personal mirror/escape coefficient from the reader's before/after history.

    Returns a float from -1.0 (confirmed mirror reader) to +1.0 (confirmed escape reader).
    Returns None if there are fewer than min_events with both pre- and post-state captured
    in the reader's current emotional zone — caller falls back to population-level boosts.

    How it works:
      - Find all past reads where emotional_state is in the same zone as current_state
        AND post_emotional_state was captured.
      - Compute delta = post_emotional_state - emotional_state for each.
        Positive delta: the book shifted the reader's mood upward (escape pattern).
        Negative delta: the book deepened it (mirror pattern).
      - Average the deltas. Normalize to [-1, 1] by dividing by 2
        (so an average shift of ±2 points maps to a coefficient of ±1).
    """
    zone = _state_zone(current_state)
    relevant = [
        e for e in events
        if e.post_emotional_state is not None
        and _state_zone(e.emotional_state) == zone
    ]
    if len(relevant) < min_events:
        return None

    deltas = [e.post_emotional_state - e.emotional_state for e in relevant]
    avg_delta = sum(deltas) / len(deltas)
    return max(-1.0, min(1.0, avg_delta / 2.0))


# ---------------------------------------------------------------------------
# Stage 3 — State modulation (now personalised)
# ---------------------------------------------------------------------------

def modulate_for_state(
    affinities: dict[str, NeedAffinity],
    state: ReadingState,
    now: Optional[datetime] = None,
    events: Optional[list[ReadEvent]] = None,
) -> dict[str, float]:
    """Stage 3: boost needs that match the reader's emotional state and reading style.

    What changed from v1:
      Previously this always applied MIRROR_BOOSTS (population assumption: sad reader
      wants wound-visible books). Now it learns whether this specific reader uses books
      as a mirror or as an escape, using their own before/after emotional data.

    Three-way decision:
      1. No before/after data yet (style=None) → use MIRROR_BOOSTS (same as before)
      2. Confirmed mirror reader (style < 0)   → amplify MIRROR_BOOSTS slightly
      3. Escape reader (style ≥ 0)             → blend toward ESCAPE_BOOSTS

    Blending for escape readers:
      effective_boost[need] = mirror[need] + style × (escape[need] - mirror[need])
      When style=0 this equals mirror[need] (no change from v1 at the threshold).
      When style=1 this equals escape[need] (full escape pattern).

    If state is stale (captured >48h ago), no modulation is applied at all.
    The result is normalised to sum to 1.0 before being dot-producted with book weights.
    """
    now = now or datetime.now(timezone.utc)

    if state.is_stale(now):
        boosts: dict[str, float] = {}
    else:
        mirror = MIRROR_BOOSTS.get(state.emotional_state, {})
        style = compute_personal_style(events or [], state.emotional_state)

        if style is None:
            # Not enough before/after data — use population-level mirror boosts
            boosts = mirror
        elif style < 0:
            # Confirmed mirror reader: amplify MIRROR_BOOSTS (up to 1.3× for style=-1)
            amp = 1 + abs(style) * 0.3
            boosts = {need: v * amp for need, v in mirror.items()}
        else:
            # Escape reader: linearly blend MIRROR_BOOSTS → ESCAPE_BOOSTS by style
            escape = ESCAPE_BOOSTS.get(state.emotional_state, {})
            all_needs = set(mirror) | set(escape)
            boosts = {
                need: mirror.get(need, 1.0) + style * (escape.get(need, 1.0) - mirror.get(need, 1.0))
                for need in all_needs
            }

    modulated: dict[str, float] = {}
    for need in NEEDS:
        base = affinity_score(affinities.get(need, NeedAffinity(need=need)))
        if need in state.active_need_ids:
            boost = 2.0           # reader explicitly requested this need
        elif need in boosts:
            boost = boosts[need]  # learned or default state boost
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
    needs_str = " and ".join(f'"{ n.replace("_", " ")}"' for n in top_needs)
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

    events is passed to modulate_for_state so it can compute the personal
    reading style coefficient from before/after emotional data.
    """
    now = now or datetime.now(timezone.utc)

    affinities    = compute_all_affinities(events, now)                    # Stages 1 + 2
    reader_vector = modulate_for_state(affinities, state, now, events)    # Stage 3
    ranked        = rank_books(reader_vector, candidate_books)             # Stage 4

    return ranked
