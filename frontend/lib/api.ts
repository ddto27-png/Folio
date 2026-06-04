// api.ts — all HTTP calls from the frontend to the FastAPI backend.
// Every function in this file talks to one endpoint in main.py.
// The base URL is set via the NEXT_PUBLIC_API_URL environment variable
// so it can point to localhost in development and Railway in production.

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

// A single book recommendation returned by the scoring engine.
// match_score is 0–1 (higher = better fit), displayed as a percentage.
// why_text is the Claude-generated sentence explaining why this book fits.
// top_need_ids are the 1–2 psychological needs driving the match (for NeedBadge).
export interface Recommendation {
  book_id: string
  title: string
  author: string | null
  cover_url: string | null
  match_score: number
  top_need_ids: number[]
  why_text: string
}

// A book the user has saved to their wishlist.
// rank is the current position sorted by match score.
export interface WishlistItem {
  book_id: string
  title: string
  author: string | null
  cover_url: string | null
  match_score: number | null
  rank: number | null
  need_ids_matched: number[] | null
}

// One result from the book search endpoint.
// in_catalog=true means it's already in our DB with need tags.
// in_catalog=false means it came from Open Library and must be created first.
// ol_key is the Open Library work key used to fetch the description on creation.
export interface BookSearchResult {
  id: string | null       // null if not yet in our catalog
  title: string
  author: string | null
  cover_url: string | null
  pub_year: number | null
  in_catalog: boolean
  ol_key: string | null   // e.g. "/works/OL123W"
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

// Fetch the top book recommendations for a user.
// Triggers the full 4-stage scoring pipeline on the backend.
export async function getRecommendations(userId: string): Promise<Recommendation[]> {
  const res = await fetch(`${API_URL}/users/${userId}/recommendations`)
  if (!res.ok) throw new Error('Failed to fetch recommendations')
  return res.json()
}

// Fetch the user's saved wishlist, sorted by current match score.
export async function getWishlist(userId: string): Promise<WishlistItem[]> {
  const res = await fetch(`${API_URL}/users/${userId}/wishlist`)
  if (!res.ok) throw new Error('Failed to fetch wishlist')
  return res.json()
}

// Log a read event for a user. Used in two places:
//   - Onboarding: logs past reads to seed the user's psychological profile.
//     Passes occurred_at backdated by however long ago they read it.
//   - LogReadModal: logs a read from the recommendations page (no occurred_at,
//     defaults to now on the backend).
// After logging, the Supabase trigger recomputes affinities automatically.
export async function logRead(
  userId: string,
  data: { book_id: string; signal_type: string; pct_read: number; emotional_state: number; occurred_at?: string }
) {
  const res = await fetch(`${API_URL}/users/${userId}/reads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to log read')
  return res.json()
}

// Search for books by title. Returns up to 8 results combining:
//   1. Books already in our Supabase catalog (shown first, in_catalog=true)
//   2. Books from Open Library (fills remaining slots, in_catalog=false)
// The backend deduplicates results by title.
export async function searchBooks(q: string): Promise<BookSearchResult[]> {
  if (q.trim().length < 2) return []
  const res = await fetch(`${API_URL}/books/search?q=${encodeURIComponent(q)}`)
  if (!res.ok) return []
  return res.json()
}

// Add a book to our catalog if it doesn't already exist.
// Called during onboarding when the user picks an Open Library result (in_catalog=false).
// The backend fetches the book's description from Open Library, inserts the book,
// then calls Claude Haiku to tag it with psychological need weights.
// Returns the new book's ID so we can immediately log a read event against it.
export async function findOrCreateBook(book: {
  title: string
  author: string | null
  cover_url: string | null
  pub_year: number | null
  ol_key: string | null
}): Promise<{ id: string; title: string; author: string | null; cover_url: string | null }> {
  const res = await fetch(`${API_URL}/books/find-or-create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(book),
  })
  if (!res.ok) throw new Error('Failed to find or create book')
  return res.json()
}
