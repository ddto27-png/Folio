// recommendations/page.tsx — the main "For you" page showing personalised book recommendations.
//
// On load it:
//   1. Checks for an active Supabase session (redirects to "/" if none)
//   2. Detects if the user is a guest (anonymous session) and shows a sign-up banner
//   3. Fetches recommendations from the backend (triggers the full scoring pipeline)
//   4. Renders a BookCard for each result
//
// The onReadLogged callback is passed to each BookCard so that when the user
// logs a read via the LogReadModal, the recommendation list refreshes automatically
// to reflect the updated psychological profile.

'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { getRecommendations, type Recommendation } from '@/lib/api'
import { BookCard } from '@/components/BookCard'
import { NavBar } from '@/components/NavBar'

export default function RecommendationsPage() {
  const router = useRouter()
  const [userId, setUserId] = useState<string | null>(null)
  const [isGuest, setIsGuest] = useState(false)          // true for anonymous Supabase sessions
  const [books, setBooks] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Fetches recommendations from GET /users/{user_id}/recommendations.
  // Wrapped in useCallback so it can be passed as a stable prop to BookCard
  // without re-creating on every render.
  const fetchRecs = useCallback(async (uid: string) => {
    setLoading(true)
    setError('')
    try {
      const data = await getRecommendations(uid)
      setBooks(data)
    } catch {
      setError('Could not load recommendations. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }, [])

  // On mount: verify session, detect guest status, and load recommendations.
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.push('/')
        return
      }
      const uid = data.session.user.id
      setUserId(uid)
      setIsGuest(data.session.user.is_anonymous ?? false)
      fetchRecs(uid)
    })
  }, [router, fetchRecs])

  return (
    <>
      <NavBar />
      <main className="max-w-2xl mx-auto px-4 py-8">

        {/* Guest banner — prompts anonymous users to create an account
            so their reads are preserved if they clear the browser session */}
        {isGuest && (
          <div className="flex items-center justify-between bg-amber-50 border border-amber-100 rounded-xl px-4 py-3 mb-6 text-sm">
            <span className="text-amber-800">You're browsing as a guest.</span>
            <button
              onClick={() => router.push('/')}
              className="text-amber-600 font-semibold hover:text-amber-700 transition"
            >
              Create account →
            </button>
          </div>
        )}

        <h2 className="font-serif text-2xl font-semibold text-gray-900 mb-1">For you</h2>
        <p className="text-sm text-gray-400 mb-6">Matched to your psychological needs right now.</p>

        {/* Skeleton loading state — 5 placeholder cards while data loads */}
        {loading && (
          <div className="flex flex-col gap-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="bg-white rounded-2xl h-36 animate-pulse border border-gray-100" />
            ))}
          </div>
        )}

        {/* Error state — shown if the backend is unreachable */}
        {error && (
          <div className="bg-red-50 text-red-700 rounded-xl p-4 text-sm">{error}</div>
        )}

        {/* Empty state — shown if the backend returned no results (e.g. user skipped onboarding) */}
        {!loading && !error && books.length === 0 && (
          <div className="text-center py-16">
            <p className="text-gray-400 text-sm">No recommendations yet.</p>
            <p className="text-gray-400 text-sm mt-1">Log some books you've read to get started.</p>
          </div>
        )}

        {/* Recommendation list — one BookCard per result */}
        <div className="flex flex-col gap-4">
          {books.map(book => (
            <BookCard
              key={book.book_id}
              bookId={book.book_id}
              title={book.title}
              author={book.author}
              coverUrl={book.cover_url}
              matchScore={book.match_score}
              topNeedIds={book.top_need_ids}
              whyText={book.why_text}
              userId={userId ?? ''}
              // After the user logs a read via the modal, refresh the whole list
              onReadLogged={() => userId && fetchRecs(userId)}
            />
          ))}
        </div>
      </main>
    </>
  )
}
