const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Recommendation {
  book_id: string
  title: string
  author: string | null
  cover_url: string | null
  match_score: number
  top_need_ids: number[]
  why_text: string
}

export interface WishlistItem {
  book_id: string
  title: string
  author: string | null
  cover_url: string | null
  match_score: number | null
  rank: number | null
  need_ids_matched: number[] | null
}

export async function getRecommendations(userId: string): Promise<Recommendation[]> {
  const res = await fetch(`${API_URL}/users/${userId}/recommendations`)
  if (!res.ok) throw new Error('Failed to fetch recommendations')
  return res.json()
}

export async function getWishlist(userId: string): Promise<WishlistItem[]> {
  const res = await fetch(`${API_URL}/users/${userId}/wishlist`)
  if (!res.ok) throw new Error('Failed to fetch wishlist')
  return res.json()
}

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

export interface BookSearchResult {
  id: string | null
  title: string
  author: string | null
  cover_url: string | null
  pub_year: number | null
  in_catalog: boolean
  ol_key: string | null
}

export async function searchBooks(q: string): Promise<BookSearchResult[]> {
  if (q.trim().length < 2) return []
  const res = await fetch(`${API_URL}/books/search?q=${encodeURIComponent(q)}`)
  if (!res.ok) return []
  return res.json()
}

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
