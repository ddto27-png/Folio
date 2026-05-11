-- =============================================================================
-- Folio — Row Level Security
-- =============================================================================
-- Run this immediately after schema.sql in Supabase's SQL Editor.
-- Rule: users can only see and touch their own data. Period.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Enable RLS on every table
-- ---------------------------------------------------------------------------

alter table users            enable row level security;
alter table reads            enable row level security;
alter table reading_state    enable row level security;
alter table need_affinity    enable row level security;
alter table recommendations  enable row level security;
alter table wishlist         enable row level security;

-- books and book_need_tags are public catalogue data — anyone can read,
-- only a service role (your backend) can write.
alter table books            enable row level security;
alter table book_need_tags   enable row level security;


-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------

-- You can see your own row
create policy "users: select own"
    on users for select
    using (auth.uid() = id);

-- You can update your own row (display_name, onboarding_answers)
create policy "users: update own"
    on users for update
    using (auth.uid() = id);

-- Supabase auth creates the row automatically on sign-up via a trigger (see below).
-- Regular users never INSERT directly into this table.


-- ---------------------------------------------------------------------------
-- reads
-- ---------------------------------------------------------------------------

create policy "reads: select own"
    on reads for select
    using (auth.uid() = user_id);

create policy "reads: insert own"
    on reads for insert
    with check (auth.uid() = user_id);

create policy "reads: update own"
    on reads for update
    using (auth.uid() = user_id);

create policy "reads: delete own"
    on reads for delete
    using (auth.uid() = user_id);


-- ---------------------------------------------------------------------------
-- reading_state
-- ---------------------------------------------------------------------------

create policy "reading_state: select own"
    on reading_state for select
    using (auth.uid() = user_id);

create policy "reading_state: insert own"
    on reading_state for insert
    with check (auth.uid() = user_id);

create policy "reading_state: update own"
    on reading_state for update
    using (auth.uid() = user_id);


-- ---------------------------------------------------------------------------
-- need_affinity
-- ---------------------------------------------------------------------------

-- Read-only for the user — the backend (service role) writes this,
-- not the client directly.
create policy "need_affinity: select own"
    on need_affinity for select
    using (auth.uid() = user_id);


-- ---------------------------------------------------------------------------
-- recommendations
-- ---------------------------------------------------------------------------

create policy "recommendations: select own"
    on recommendations for select
    using (auth.uid() = user_id);


-- ---------------------------------------------------------------------------
-- wishlist
-- ---------------------------------------------------------------------------

create policy "wishlist: select own"
    on wishlist for select
    using (auth.uid() = user_id);

create policy "wishlist: insert own"
    on wishlist for insert
    with check (auth.uid() = user_id);

create policy "wishlist: update own"
    on wishlist for update
    using (auth.uid() = user_id);

create policy "wishlist: delete own"
    on wishlist for delete
    using (auth.uid() = user_id);


-- ---------------------------------------------------------------------------
-- books  (public catalogue — readable by anyone, writable only by service role)
-- ---------------------------------------------------------------------------

create policy "books: public read"
    on books for select
    using (true);

-- No insert/update/delete policy for regular users.
-- Your backend uses the service role key to add books — it bypasses RLS entirely.


-- ---------------------------------------------------------------------------
-- book_need_tags  (same as books — public read, service role writes)
-- ---------------------------------------------------------------------------

create policy "book_need_tags: public read"
    on book_need_tags for select
    using (true);


-- ---------------------------------------------------------------------------
-- needs table (already has data, no RLS needed — it's a static enum table)
-- The needs table is read-only reference data. No user writes to it.
-- ---------------------------------------------------------------------------

-- needs doesn't have user_id so we just make it publicly readable
alter table needs enable row level security;

create policy "needs: public read"
    on needs for select
    using (true);


-- ---------------------------------------------------------------------------
-- Auto-create a users row when someone signs up via Supabase Auth
-- ---------------------------------------------------------------------------
-- Without this, auth.users and your public.users table get out of sync.

create or replace function handle_new_auth_user()
returns trigger language plpgsql security definer as $$
begin
    insert into public.users (id, email, created_at)
    values (new.id, new.email, now())
    on conflict (id) do nothing;
    return new;
end;
$$;

create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function handle_new_auth_user();
