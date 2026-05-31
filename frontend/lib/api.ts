const API_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

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

export interface LogReadBody {
  book_id: string
  signal_type: string
  pct_read?: number
  emotional_state: number
}

export const api = {
  logRead: (userId: string, body: LogReadBody) =>
    request(`/users/${userId}/reads`, { method: 'POST', body: JSON.stringify(body) }),

  getRecommendations: (userId: string, limit = 10) =>
    request<Recommendation[]>(`/users/${userId}/recommendations?limit=${limit}`),

  getWishlist: (userId: string) =>
    request<WishlistItem[]>(`/users/${userId}/wishlist`),
}
