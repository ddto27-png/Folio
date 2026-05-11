"""
Folio scoring engine — tests
Run with: python -m pytest test_scoring.py -v
"""

from datetime import datetime, timedelta, timezone
import pytest
from scoring import (
    ReadEvent, ReadingState, BookProfile, NeedAffinity,
    signal_contribution, compute_affinity, affinity_score,
    modulate_for_state, match_score, rank_books, full_pipeline,
    NEEDS,
)

UTC = timezone.utc
NOW = datetime(2025, 1, 1, tzinfo=UTC)

def make_event(signal="star_5", pct=1.0, state=3, need_w=None, days_ago=0):
    return ReadEvent(
        book_id="b1",
        signal_type=signal,
        pct_read=pct,
        emotional_state=state,
        occurred_at=NOW - timedelta(days=days_ago),
        book_need_weights=need_w or {"being_chosen": 0.9},
    )


# ---------------------------------------------------------------------------
# Stage 1 — signal_contribution
# ---------------------------------------------------------------------------

class TestSignalContribution:

    def test_5star_full_read_positive(self):
        e = make_event("star_5", pct=1.0, state=3)
        c = signal_contribution(e, "being_chosen")
        assert c > 0

    def test_1star_negative(self):
        e = make_event("star_1", pct=1.0, state=3)
        c = signal_contribution(e, "being_chosen")
        assert c < 0

    def test_3star_near_zero(self):
        e = make_event("star_3", pct=1.0, state=3)
        c = signal_contribution(e, "being_chosen")
        assert abs(c) < 0.2   # should be weak

    def test_low_read_pct_dampens(self):
        high = signal_contribution(make_event("star_5", pct=1.0), "being_chosen")
        low  = signal_contribution(make_event("star_5", pct=0.2), "being_chosen")
        assert high > low

    def test_emotional_alignment_amplifies(self):
        # State 2 (sad) aligns with being_chosen → should amplify
        aligned     = signal_contribution(make_event("star_5", state=2), "being_chosen")
        not_aligned = signal_contribution(make_event("star_5", state=4), "being_chosen")
        assert aligned > not_aligned

    def test_need_not_in_book_is_zero(self):
        e = make_event("star_5", need_w={"being_chosen": 0.9})
        c = signal_contribution(e, "world_larger")
        assert c == 0.0

    def test_abandoned_is_negative(self):
        e = make_event("abandoned", pct=0.3)
        c = signal_contribution(e, "being_chosen")
        assert c < 0

    def test_reread_strong_positive(self):
        reread  = signal_contribution(make_event("re_read",  pct=1.0), "being_chosen")
        star4   = signal_contribution(make_event("star_4",   pct=1.0), "being_chosen")
        assert reread > star4


# ---------------------------------------------------------------------------
# Stage 2 — compute_affinity
# ---------------------------------------------------------------------------

class TestComputeAffinity:

    def test_no_events_returns_zeros(self):
        na = compute_affinity([], "being_chosen", NOW)
        assert na.base_score == 0.0
        assert na.decayed_score == 0.0

    def test_positive_events_raise_score(self):
        events = [make_event("star_5", days_ago=i) for i in range(5)]
        na = compute_affinity(events, "being_chosen", NOW)
        assert na.base_score > 0
        assert na.decayed_score > 0

    def test_old_reads_decay(self):
        recent = [make_event("star_5", days_ago=5)]
        old    = [make_event("star_5", days_ago=500)]
        na_recent = compute_affinity(recent, "being_chosen", NOW)
        na_old    = compute_affinity(old,    "being_chosen", NOW)
        assert na_recent.decayed_score > na_old.decayed_score

    def test_score_clamped_0_to_1(self):
        events = [make_event("star_5") for _ in range(50)]
        na = compute_affinity(events, "being_chosen", NOW)
        assert 0.0 <= na.base_score <= 1.0
        assert 0.0 <= na.decayed_score <= 1.0

    def test_volatile_reader_has_nonzero_volatility(self):
        # Alternate between loving and hating books on this need
        events = []
        for i in range(12):
            sig = "star_5" if i % 2 == 0 else "star_1"
            events.append(make_event(sig, days_ago=i*7))
        na = compute_affinity(events, "being_chosen", NOW)
        assert na.volatility > 0.0

    def test_consistent_reader_low_volatility(self):
        events = [make_event("star_5", days_ago=i*7) for i in range(12)]
        na = compute_affinity(events, "being_chosen", NOW)
        # All same signal → low volatility
        assert na.volatility < 0.5


# ---------------------------------------------------------------------------
# Stage 3 — modulate_for_state
# ---------------------------------------------------------------------------

class TestModulateForState:

    def _make_affinities(self, score=0.5):
        return {
            need: NeedAffinity(need=need, base_score=score, decayed_score=score)
            for need in NEEDS
        }

    def test_normalised_sums_to_one(self):
        affinities = self._make_affinities(0.5)
        state = ReadingState(emotional_state=3, captured_at=NOW)
        vec = modulate_for_state(affinities, state, NOW)
        assert abs(sum(vec.values()) - 1.0) < 1e-6

    def test_active_need_boosted_highest(self):
        affinities = self._make_affinities(0.5)
        state = ReadingState(
            emotional_state=3,
            active_need_ids=["being_chosen"],
            captured_at=NOW,
        )
        vec = modulate_for_state(affinities, state, NOW)
        assert vec["being_chosen"] == max(vec.values())

    def test_stale_state_no_boost(self):
        affinities = self._make_affinities(0.5)
        stale_time = NOW - timedelta(hours=72)
        state = ReadingState(
            emotional_state=1,   # crisis — should boost wound_visible etc
            active_need_ids=[],
            captured_at=stale_time,
        )
        vec = modulate_for_state(affinities, state, NOW)
        # All values should be equal (uniform, no modulation)
        values = list(vec.values())
        assert max(values) - min(values) < 1e-6

    def test_state_1_boosts_wound_visible(self):
        affinities = self._make_affinities(0.5)
        state = ReadingState(emotional_state=1, captured_at=NOW)
        vec = modulate_for_state(affinities, state, NOW)
        # wound_visible gets 2.0× boost in state 1
        assert vec["wound_visible"] > vec["world_larger"]

    def test_state_5_boosts_being_chosen(self):
        affinities = self._make_affinities(0.5)
        state = ReadingState(emotional_state=5, captured_at=NOW)
        vec = modulate_for_state(affinities, state, NOW)
        assert vec["being_chosen"] > vec["surviving"]


# ---------------------------------------------------------------------------
# Stage 4 — match_score
# ---------------------------------------------------------------------------

class TestMatchScore:

    def _reader_vec(self, **overrides):
        base = {n: 1/len(NEEDS) for n in NEEDS}
        base.update(overrides)
        total = sum(base.values())
        return {n: v/total for n, v in base.items()}

    def test_well_matched_book_scores_high(self):
        reader = self._reader_vec(being_chosen=0.8)
        book = BookProfile(
            book_id="romance",
            need_weights={"being_chosen": 0.9},
            ratings_count=5000,
        )
        score, _ = match_score(reader, book)
        assert score > 0.4

    def test_mismatched_book_scores_low(self):
        reader = self._reader_vec(being_chosen=0.8)
        book = BookProfile(
            book_id="history",
            need_weights={"making_sense_history": 0.9},
            ratings_count=5000,
        )
        score, _ = match_score(reader, book)
        # Low match — reader wants belonging, book serves history need
        assert score < 0.3

    def test_cold_book_pulled_toward_prior(self):
        reader = self._reader_vec(being_chosen=0.8)
        warm_book = BookProfile("warm", {"being_chosen": 0.9}, ratings_count=500)
        cold_book = BookProfile("cold", {"being_chosen": 0.9}, ratings_count=3)
        warm_score, _ = match_score(reader, warm_book)
        cold_score, _ = match_score(reader, cold_book)
        # Cold book pulled toward 0.5 prior → lower than well-evidenced book
        assert warm_score > cold_score

    def test_top_needs_returned(self):
        reader = self._reader_vec(being_chosen=0.6, world_larger=0.3)
        book = BookProfile("b", {"being_chosen": 0.8, "world_larger": 0.6}, ratings_count=100)
        _, top = match_score(reader, book)
        assert len(top) == 2
        assert "being_chosen" in top

    def test_novelty_discount_applied(self):
        reader = self._reader_vec(being_chosen=0.8)
        fresh = BookProfile("fresh", {"being_chosen": 0.9}, ratings_count=500, recently_read_overlap=0.0)
        stale = BookProfile("stale", {"being_chosen": 0.9}, ratings_count=500, recently_read_overlap=1.0)
        fresh_s, _ = match_score(reader, fresh)
        stale_s, _ = match_score(reader, stale)
        assert fresh_s > stale_s


# ---------------------------------------------------------------------------
# rank_books
# ---------------------------------------------------------------------------

class TestRankBooks:

    def test_sorted_descending(self):
        reader = {n: 1/len(NEEDS) for n in NEEDS}
        reader["being_chosen"] = 0.7
        books = [
            BookProfile("a", {"being_chosen": 0.9}, 500),
            BookProfile("b", {"making_sense_history": 0.9}, 500),
            BookProfile("c", {"being_chosen": 0.5}, 500),
        ]
        ranked = rank_books(reader, books)
        scores = [r[1] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_returns_all_books(self):
        reader = {n: 1/len(NEEDS) for n in NEEDS}
        books = [BookProfile(str(i), {}, 100) for i in range(10)]
        ranked = rank_books(reader, books)
        assert len(ranked) == 10


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def test_pipeline_returns_ranked_books(self):
        events = [
            ReadEvent("b1", "star_5", 1.0, 2, NOW - timedelta(days=10),
                      {"being_chosen": 0.9}),
            ReadEvent("b2", "star_4", 0.8, 2, NOW - timedelta(days=20),
                      {"being_chosen": 0.7, "wound_visible": 0.4}),
        ]
        state = ReadingState(emotional_state=2, captured_at=NOW)
        books = [
            BookProfile("romance", {"being_chosen": 0.9}, 5000),
            BookProfile("thriller", {"procedural_resolution": 0.9}, 5000),
            BookProfile("fantasy",  {"world_larger": 0.9}, 5000),
        ]
        ranked = full_pipeline(events, state, books, NOW)
        assert len(ranked) == 3
        # Romance should win — reader's signals all point to being_chosen
        assert ranked[0][0].book_id == "romance"

    def test_state_2_surfaces_wound_visible(self):
        events = [
            ReadEvent("b1", "star_5", 1.0, 3, NOW - timedelta(days=5),
                      {"being_chosen": 0.5, "wound_visible": 0.5}),
        ]
        state = ReadingState(
            emotional_state=2,
            active_need_ids=["wound_visible"],
            captured_at=NOW,
        )
        books = [
            BookProfile("grief_memoir", {"wound_visible": 0.9}, 2000),
            BookProfile("romance",      {"being_chosen": 0.9},  2000),
        ]
        ranked = full_pipeline(events, state, books, NOW)
        assert ranked[0][0].book_id == "grief_memoir"
