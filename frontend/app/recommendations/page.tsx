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
  const [books, setBooks] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.push('/')
        return
      }
      const uid = data.session.user.id
      setUserId(uid)
      fetchRecs(uid)
    })
  }, [router, fetchRecs])

  return (
    <>
      <NavBar />
      <main className="max-w-2xl mx-auto px-4 py-8">
        <h2 className="font-serif text-2xl font-semibold text-gray-900 mb-1">For you</h2>
        <p className="text-sm text-gray-400 mb-6">Matched to your psychological needs right now.</p>

        {loading && (
          <div className="flex flex-col gap-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="bg-white rounded-2xl h-36 animate-pulse border border-gray-100" />
            ))}
          </div>
        )}

        {error && (
          <div className="bg-red-50 text-red-700 rounded-xl p-4 text-sm">{error}</div>
        )}

        {!loading && !error && books.length === 0 && (
          <div className="text-center py-16">
            <p className="text-gray-400 text-sm">No recommendations yet.</p>
            <p className="text-gray-400 text-sm mt-1">Log some books you've read to get started.</p>
          </div>
        )}

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
              onReadLogged={() => userId && fetchRecs(userId)}
            />
          ))}
        </div>
      </main>
    </>
  )
}
