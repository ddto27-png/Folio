// api.ts — all HTTP calls from the frontend to the FastAPI backend.
// Every function in this file talks to one endpoint in main.py.
// The base URL is set via the NEXT_PUBLIC_API_URL environment variable
// so it can point to localhost in development and Railway in production.

import { supabase } from '@/lib/supabase'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Returns auth + content-type headers for the current Supabase session.
// User-specific endpoints require this so the backend can verify the request
// via JWT and derive the user ID — it never trusts the URL parameter.
async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token
    ? { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
    : { 'Content-Type': 'application/json' }
}

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

// One result from GET /books/search — always from our catalog.
export interface BookSearchResult {
  id: string
  title: string
  author: string | null
  cover_url: string | null
  pub_year: number | null
  in_catalog: true
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

// Fetch the top book recommendations for the current user.
// The backend derives the user ID from the JWT — the _userId param is kept
// only for call-site consistency and is not sent in the URL.
export async function getRecommendations(_userId: string): Promise<Recommendation[]> {
  const headers = await authHeaders()
  const res = await fetch(`${API_URL}/recommendations`, { headers })
  if (!res.ok) throw new Error('Failed to fetch recommendations')
  return res.json()
}

// Fetch the current user's saved wishlist, sorted by match score.
export async function getWishlist(_userId: string): Promise<WishlistItem[]> {
  const headers = await authHeaders()
  const res = await fetch(`${API_URL}/wishlist`, { headers })
  if (!res.ok) throw new Error('Failed to fetch wishlist')
  return res.json()
}

// Log a read event. The backend verifies the JWT and uses the user ID from it.
export async function logRead(
  _userId: string,
  data: { book_id: string; signal_type: string; pct_read: number; emotional_state: number; post_emotional_state?: number; occurred_at?: string }
) {
  const headers = await authHeaders()
  const res = await fetch(`${API_URL}/reads`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to log read')
  return res.json()
}

// Save the user's current emotional state and explicitly selected needs.
// The backend marks the previous reading_state row as stale and inserts a fresh one.
// Recommendations fetched after this call will immediately reflect the new state.
export async function updateReadingState(data: { emotional_state: number; active_need_ids: number[] }): Promise<void> {
  const headers = await authHeaders()
  const res = await fetch(`${API_URL}/reading-state`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update reading state')
}

// Search for books by title. Returns up to 8 results combining:
//   1. Books already in our Supabase catalog (shown first, in_catalog=true)
//   2. Books from Open Library (fills remaining slots, in_catalog=false)
// No auth needed — book search is a public catalog operation.
export async function searchBooks(q: string): Promise<BookSearchResult[]> {
  if (q.trim().length < 2) return []
  const res = await fetch(`${API_URL}/books/search?q=${encodeURIComponent(q)}`)
  if (!res.ok) return []
  return res.json()
}

// Request a book be added to the catalog (processed by the nightly ingest job).
// Requires auth — all users have an anonymous session so this is always available.
export async function requestBook(title: string, author: string | null): Promise<void> {
  const headers = await authHeaders()
  await fetch(`${API_URL}/books/request`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ title, author }),
  })
}
