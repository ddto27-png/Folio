-- =============================================================================
-- Migration 001 — book_requests table + post_emotional_state field
-- =============================================================================
-- Run in Supabase SQL editor or via psql.
-- Safe to re-run: uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- 1. Add post_emotional_state to reads
--    The Python scoring engine and frontend already use this field.
--    It was missing from the original schema.
-- ---------------------------------------------------------------------------

alter table reads
    add column if not exists post_emotional_state smallint
        check (post_emotional_state between 1 and 5);


-- ---------------------------------------------------------------------------
-- 2. book_requests — collects titles users searched for that aren't in catalog
--    Deduplicated by (lower(title), lower(author)).
--    status: 'pending' | 'ingested' | 'failed'
-- ---------------------------------------------------------------------------

create table if not exists book_requests (
    id            uuid primary key default gen_random_uuid(),
    title         text not null,
    author        text,
    request_count int  not null default 1,
    status        text not null default 'pending'
                      check (status in ('pending', 'ingested', 'failed')),
    first_requested_at  timestamptz default now(),
    last_requested_at   timestamptz default now()
);

-- Unique on normalised title + author so duplicates increment the counter
create unique index if not exists book_requests_title_author_idx
    on book_requests (lower(title), lower(coalesce(author, '')));

-- Index for the nightly job query (pending, sorted by request_count desc)
create index if not exists book_requests_pending_idx
    on book_requests (status, request_count desc)
    where status = 'pending';


-- ---------------------------------------------------------------------------
-- 3. Upsert function — called by the /books/request endpoint.
--    Inserts on first request; increments counter and updates timestamp on repeat.
-- ---------------------------------------------------------------------------

create or replace function upsert_book_request(p_title text, p_author text)
returns void
language sql as $$
    insert into book_requests (title, author, request_count, last_requested_at)
    values (p_title, p_author, 1, now())
    on conflict (lower(title), lower(coalesce(author, '')))
    do update set
        request_count      = book_requests.request_count + 1,
        last_requested_at  = now()
    where book_requests.status = 'pending';
$$;


-- ---------------------------------------------------------------------------
-- 4. RLS — users can insert requests (any authenticated session, incl. anon).
--    No user can read or modify other users' requests.
--    The nightly script runs with the service role key and bypasses RLS.
-- ---------------------------------------------------------------------------

alter table book_requests enable row level security;

-- Any authenticated session (including anonymous Supabase sessions) may insert.
-- The upsert_book_request function runs as the caller, so this policy applies.
create policy "authenticated users can request books"
    on book_requests for insert
    to authenticated
    with check (true);

-- No direct select/update/delete for client sessions — nightly job uses service role.
