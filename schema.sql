-- =============================================================================
-- Folio — Scoring Engine (Postgres / Supabase)
-- =============================================================================
-- Mirrors the Python pipeline exactly.
-- Run this file as a migration (psql or Supabase SQL editor).
-- Requires: pgcrypto (for gen_random_uuid), available by default on Supabase.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 0. Enums & constants
-- ---------------------------------------------------------------------------

create type signal_type as enum (
    'star_5', 'star_4', 'star_3', 'star_2', 'star_1',
    'abandoned', 're_read', 'highlighted',
    'added_wishlist', 'shared', 'clicked_rec', 'ignored_rec'
);

-- The 13 psychological needs (matches Python NEEDS list)
create table needs (
    id          smallint primary key,
    code        text unique not null,
    name        text not null,
    core_anxiety text,
    story_proof  text
);

insert into needs (id, code, name) values
    (1,  'being_chosen',           'Being perfectly chosen'),
    (2,  'surviving',              'Surviving the unsurvivable'),
    (3,  'procedural_resolution',  'Procedural resolution'),
    (4,  'moral_complexity',       'Moral complexity held'),
    (5,  'power_agency',           'Access to power and agency'),
    (6,  'wound_visible',          'The wound made visible'),
    (7,  'making_sense_history',   'Making sense of history'),
    (8,  'self_remade',            'The self can be remade'),
    (9,  'inside_power',           'Being inside power'),
    (10, 'identity_witnessed',     'Identity witnessed'),
    (11, 'world_larger',           'The world is larger'),
    (12, 'creative_kinship',       'Creative kinship'),
    (13, 'anxiety_named',          'Anxiety named and held');


-- ---------------------------------------------------------------------------
-- 1. Core tables
-- ---------------------------------------------------------------------------

create table users (
    id               uuid primary key default gen_random_uuid(),
    display_name     text,
    email            text unique,
    created_at       timestamptz default now(),
    onboarding_answers jsonb default '{}'
);

create table books (
    id               uuid primary key default gen_random_uuid(),
    title            text not null,
    author           text,
    isbn             text,
    description      text,
    cover_url        text,
    pub_year         smallint,
    ratings_count    int default 0,
    avg_rating       numeric(3,2)
);

create table book_need_tags (
    id         uuid primary key default gen_random_uuid(),
    book_id    uuid references books(id) on delete cascade,
    need_id    smallint references needs(id),
    weight     numeric(4,3) not null check (weight between 0 and 1),
    source     text default 'llm',          -- 'llm' | 'human' | 'behavioral'
    has_perpetrator boolean,                -- for wound_visible sub-dimension
    unique (book_id, need_id)
);

create table reads (
    id                    uuid primary key default gen_random_uuid(),
    user_id               uuid references users(id) on delete cascade,
    book_id               uuid references books(id),
    signal_type           signal_type not null,
    pct_read              numeric(4,3) default 1.0 check (pct_read between 0 and 1),
    emotional_state       smallint check (emotional_state between 1 and 5),
    occurred_at           timestamptz default now(),
    review_text           text
);

create table reading_state (
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid references users(id) on delete cascade,
    emotional_state   smallint check (emotional_state between 1 and 5),
    active_need_ids   smallint[] default '{}',
    captured_at       timestamptz default now(),
    is_current        boolean default true
);

-- Enforce only one current state per user
create unique index reading_state_current_idx
    on reading_state (user_id) where is_current = true;

create table need_affinity (
    id                   uuid primary key default gen_random_uuid(),
    user_id              uuid references users(id) on delete cascade,
    need_id              smallint references needs(id),
    base_score           numeric(6,4) default 0,
    decayed_score        numeric(6,4) default 0,
    volatility           numeric(6,4) default 0,
    last_updated         timestamptz default now(),
    unique (user_id, need_id)
);

create table recommendations (
    id                   uuid primary key default gen_random_uuid(),
    user_id              uuid references users(id) on delete cascade,
    book_id              uuid references books(id),
    match_score          numeric(6,4),
    top_need_ids         smallint[],
    why_text             text,
    was_shown            boolean default false,
    was_acted_on         boolean default false,
    generated_at         timestamptz default now()
);

create table wishlist (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid references users(id) on delete cascade,
    book_id          uuid references books(id),
    match_score      numeric(6,4),
    need_ids_matched smallint[],
    rank             int,
    added_at         timestamptz default now(),
    score_updated_at timestamptz default now(),
    unique (user_id, book_id)
);


-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

create index reads_user_occurred on reads (user_id, occurred_at desc);
create index reads_book on reads (book_id);
create index book_need_tags_book on book_need_tags (book_id);
create index book_need_tags_need on book_need_tags (need_id);
create index need_affinity_user on need_affinity (user_id);
create index recommendations_user on recommendations (user_id, generated_at desc);
create index wishlist_user_rank on wishlist (user_id, rank);


-- ---------------------------------------------------------------------------
-- 2. Helper constants as a function (avoids magic numbers in queries)
-- ---------------------------------------------------------------------------

create or replace function scoring_constants()
returns table (key text, val numeric)
language sql immutable as $$
    select * from (values
        ('decay_lambda',          0.005),   -- half-life ~139 days
        ('cold_book_prior',       0.2),     -- Bayesian prior for <50 ratings
        ('cold_book_threshold',   50),      -- ratings for full confidence
        ('novelty_discount',      0.15)     -- penalty for overlap with recent reads
    ) t(key, val);
$$;


-- ---------------------------------------------------------------------------
-- 3. Stage 1+2 — Compute need_affinity for one user × one need
-- ---------------------------------------------------------------------------

create or replace function compute_need_affinity(
    p_user_id  uuid,
    p_need_id  smallint
)
returns table (
    base_score    numeric,
    decayed_score numeric,
    volatility    numeric
)
language sql stable as $$
with

-- Signal weights (mirrors Python SIGNAL_WEIGHTS)
signal_weights (sig, w) as (
    values
        ('star_5'::signal_type,         1.0),
        ('star_4'::signal_type,         0.6),
        ('star_3'::signal_type,         0.1),
        ('star_2'::signal_type,        -0.4),
        ('star_1'::signal_type,        -0.8),
        ('abandoned'::signal_type,     -0.5),
        ('re_read'::signal_type,        0.9),
        ('highlighted'::signal_type,    0.3),
        ('added_wishlist'::signal_type, 0.2),
        ('shared'::signal_type,         0.25),
        ('clicked_rec'::signal_type,    0.1),
        ('ignored_rec'::signal_type,   -0.05)
),

-- State→need alignment boosts (mirrors Python STATE_BOOSTS)
state_boosts (state, need_code, boost) as (
    values
        (1, 'wound_visible',        2.0),
        (1, 'anxiety_named',        1.4),
        (1, 'surviving',            1.4),
        (2, 'wound_visible',        1.4),
        (2, 'being_chosen',         1.4),
        (3, 'making_sense_history', 1.4),
        (3, 'moral_complexity',     1.4),
        (3, 'creative_kinship',     1.4),
        (4, 'world_larger',         1.4),
        (4, 'power_agency',         1.4),
        (4, 'inside_power',         1.4),
        (4, 'self_remade',          1.4),
        (5, 'being_chosen',         1.4),
        (5, 'identity_witnessed',   1.4),
        (5, 'creative_kinship',     1.4)
),

-- Finish multiplier
finish_mult (pct_min, pct_max, mult) as (
    values
        (0.9,  1.0, 1.0),
        (0.5,  0.9, 0.6),
        (0.0,  0.5, 0.3)
),

-- All read events for this user that have a tag for this need
raw_events as (
    select
        r.occurred_at,
        sw.w                                           as sig_w,
        coalesce(bnt.weight, 0)                        as need_w,
        case
            when r.pct_read >= 0.9 then 1.0
            when r.pct_read >= 0.5 then 0.6
            else 0.3
        end                                            as finish_m,
        -- emotional alignment: scale boost into [0.7, 1.3]
        coalesce(sb.boost, 1.0) * 0.3 + 0.7           as align_m
    from reads r
    join signal_weights sw on sw.sig = r.signal_type
    left join book_need_tags bnt
        on bnt.book_id = r.book_id and bnt.need_id = p_need_id
    left join needs n on n.id = p_need_id
    left join state_boosts sb
        on sb.state = r.emotional_state and sb.need_code = n.code
    where r.user_id = p_user_id
),

-- Stage 1: raw contribution per event
contributions as (
    select
        occurred_at,
        sig_w * need_w * finish_m * align_m as contribution,
        exp(-0.005 * extract(epoch from (now() - occurred_at)) / 86400.0) as decay_factor
    from raw_events
),

-- Stage 2: aggregate
agg as (
    select
        count(*)::numeric                           as n,
        sum(contribution)                           as raw_sum,
        sum(contribution * decay_factor)            as decayed_sum,
        -- Volatility from last 12 events
        stddev_pop(contribution)
            filter (where rn <= 12)                 as std12,
        avg(contribution)
            filter (where rn <= 12)                 as mean12
    from (
        select *,
               row_number() over (order by occurred_at desc) as rn
        from contributions
    ) c
)

select
    -- base_score: diminishing returns, clamped [0,1]
    greatest(0, least(1,
        agg.raw_sum / nullif(power(agg.n, 0.6), 0)
    ))::numeric(6,4)                                            as base_score,

    -- decayed_score
    greatest(0, least(1,
        agg.decayed_sum / nullif(power(agg.n, 0.6), 0)
    ))::numeric(6,4)                                            as decayed_score,

    -- volatility: std/mean, clamped [0,1]
    least(1, greatest(0,
        coalesce(agg.std12 / nullif(abs(agg.mean12), 0), 0)
    ))::numeric(6,4)                                            as volatility

from agg;
$$;


-- ---------------------------------------------------------------------------
-- 4. Refresh need_affinity table for a user (call after each new read event)
-- ---------------------------------------------------------------------------

create or replace function refresh_user_affinity(p_user_id uuid)
returns void
language plpgsql as $$
declare
    need record;
    scores record;
begin
    for need in select id from needs loop
        select base_score, decayed_score, volatility
          into scores
          from compute_need_affinity(p_user_id, need.id);

        insert into need_affinity (user_id, need_id, base_score, decayed_score, volatility, last_updated)
        values (p_user_id, need.id, scores.base_score, scores.decayed_score, scores.volatility, now())
        on conflict (user_id, need_id) do update
            set base_score    = excluded.base_score,
                decayed_score = excluded.decayed_score,
                volatility    = excluded.volatility,
                last_updated  = excluded.last_updated;
    end loop;
end;
$$;


-- ---------------------------------------------------------------------------
-- 5. Stage 3+4 — Match score for one user × one book
-- ---------------------------------------------------------------------------

create or replace function book_match_score(
    p_user_id   uuid,
    p_book_id   uuid,
    p_overlap   numeric default 0  -- recently_read_overlap (0–1), pass from app
)
returns table (
    match_score  numeric,
    top_need_ids smallint[]
)
language sql stable as $$
with

-- Current reading state (null if stale >48h)
cur_state as (
    select emotional_state, active_need_ids
    from reading_state
    where user_id = p_user_id
      and is_current = true
      and captured_at > now() - interval '48 hours'
    limit 1
),

-- State boosts (same table as in compute_need_affinity)
state_boosts (state, need_code, boost) as (
    values
        (1, 'wound_visible',        2.0),
        (1, 'anxiety_named',        1.4),
        (1, 'surviving',            1.4),
        (2, 'wound_visible',        1.4),
        (2, 'being_chosen',         1.4),
        (3, 'making_sense_history', 1.4),
        (3, 'moral_complexity',     1.4),
        (3, 'creative_kinship',     1.4),
        (4, 'world_larger',         1.4),
        (4, 'power_agency',         1.4),
        (4, 'inside_power',         1.4),
        (4, 'self_remade',          1.4),
        (5, 'being_chosen',         1.4),
        (5, 'identity_witnessed',   1.4),
        (5, 'creative_kinship',     1.4)
),

-- Reader affinity vector (from pre-computed table)
reader as (
    select
        na.need_id,
        n.code as need_code,
        -- Blend: alpha × decayed + (1-alpha) × base
        (0.3 + 0.4 * na.volatility) * na.decayed_score
        + (1 - (0.3 + 0.4 * na.volatility)) * na.base_score  as affinity
    from need_affinity na
    join needs n on n.id = na.need_id
    where na.user_id = p_user_id
),

-- Stage 3: modulate by state
modulated as (
    select
        r.need_id,
        r.need_code,
        r.affinity *
            case
                -- Explicit active need: 2× boost
                when cs.active_need_ids @> array[r.need_id]  then 2.0
                -- Implicit state alignment
                when sb.boost is not null                     then sb.boost
                else 1.0
            end                                           as modulated_affinity
    from reader r
    cross join lateral (select * from cur_state limit 1) cs
    left join state_boosts sb
        on sb.state = cs.emotional_state
        and sb.need_code = r.need_code
),

-- Normalise to sum to 1
total_mod as (
    select sum(modulated_affinity) as total from modulated
),

normalised as (
    select
        m.need_id,
        m.need_code,
        m.modulated_affinity / nullif(tm.total, 0) as reader_weight
    from modulated m, total_mod tm
),

-- Book need weights
book as (
    select need_id, weight as book_weight
    from book_need_tags
    where book_id = p_book_id
),

-- Stage 4: dot product
dot as (
    select
        n.need_id,
        n.reader_weight * coalesce(b.book_weight, 0) as contribution
    from normalised n
    left join book b using (need_id)
),

raw_match as (
    select sum(contribution) as raw from dot
),

-- Cold-book Bayesian adjustment
bayes as (
    select
        rm.raw,
        least(1.0, bk.ratings_count::numeric / 50) as confidence
    from raw_match rm
    cross join books bk
    where bk.id = p_book_id
)

select
    -- Final score: Bayesian × novelty discount
    round(
        (b.confidence * b.raw + (1 - b.confidence) * 0.2)
        * (1 - 0.15 * p_overlap),
        4
    )::numeric(6,4)                                  as match_score,

    -- Top 2 contributing needs
    array(
        select need_id from dot
        order by contribution desc
        limit 2
    )::smallint[]                                     as top_need_ids

from bayes b;
$$;


-- ---------------------------------------------------------------------------
-- 6. Rank all wishlist books for a user (call to re-sort wishlist)
-- ---------------------------------------------------------------------------

create or replace function rank_wishlist(p_user_id uuid)
returns void
language plpgsql as $$
declare
    entry record;
    scored record;
    rnk int := 1;
begin
    -- Score every book in wishlist, order by score desc, update rank
    for entry in
        select w.id, w.book_id
        from wishlist w
        where w.user_id = p_user_id
        order by w.match_score desc nulls last
    loop
        select match_score, top_need_ids
          into scored
          from book_match_score(p_user_id, entry.book_id);

        update wishlist
           set match_score      = scored.match_score,
               need_ids_matched = scored.top_need_ids,
               rank             = rnk,
               score_updated_at = now()
         where id = entry.id;

        rnk := rnk + 1;
    end loop;
end;
$$;


-- ---------------------------------------------------------------------------
-- 7. Trigger: refresh affinity + re-rank wishlist after each new read
-- ---------------------------------------------------------------------------

create or replace function on_new_read()
returns trigger language plpgsql as $$
begin
    perform refresh_user_affinity(NEW.user_id);
    perform rank_wishlist(NEW.user_id);
    return NEW;
end;
$$;

create trigger trg_new_read
    after insert on reads
    for each row execute function on_new_read();


-- ---------------------------------------------------------------------------
-- 8. Convenience view: ranked wishlist with book details
-- ---------------------------------------------------------------------------

create or replace view v_wishlist_ranked as
select
    w.user_id,
    w.rank,
    w.match_score,
    b.title,
    b.author,
    b.cover_url,
    w.need_ids_matched,
    w.score_updated_at,
    array_agg(n.name order by n.id) as matched_need_names
from wishlist w
join books b on b.id = w.book_id
left join lateral unnest(w.need_ids_matched) as need_id on true
left join needs n on n.id = need_id
group by w.user_id, w.rank, w.match_score, b.title, b.author,
         b.cover_url, w.need_ids_matched, w.score_updated_at
order by w.user_id, w.rank;
