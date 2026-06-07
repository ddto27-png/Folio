'use client'

import { useEffect, useState, useCallback } from 'react'
import { supabase } from '@/lib/supabase'
import { getRecommendations, type Recommendation } from '@/lib/api'
import { Header } from '@/components/Header'
import { BookCard } from '@/components/BookCard'
import { InlineBookLogger } from '@/components/InlineBookLogger'
import { NeedFilterPanel } from '@/components/NeedFilterPanel'
import { SaveProfileModal } from '@/components/SaveProfileModal'

const SKELETON_COUNT = 5

export default function Home() {
  const [userId, setUserId] = useState<string | null>(null)
  const [isAnonymous, setIsAnonymous] = useState(true)
  const [authError, setAuthError] = useState(false)
  const [books, setBooks] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(false)
  const [booksLogged, setBooksLogged] = useState(0)
  const [showSaveModal, setShowSaveModal] = useState(false)

  // On mount: restore an existing session, or silently create an anonymous one.
  // The user never sees a login screen — they're just given a session automatically.
  useEffect(() => {
    async function initSession() {
      const { data } = await supabase.auth.getSession()
      if (data.session) {
        setUserId(data.session.user.id)
        setIsAnonymous(data.session.user.is_anonymous ?? false)
      } else {
        const { data: anon, error } = await supabase.auth.signInAnonymously()
        if (error || !anon.user) {
          setAuthError(true)
        } else {
          setUserId(anon.user.id)
          setIsAnonymous(true)
        }
      }
    }
    initSession()
  }, [])

  const fetchRecs = useCallback(async (uid: string) => {
    setLoading(true)
    try {
      const data = await getRecommendations(uid)
      setBooks(data)
    } catch {
      // Backend may not be running locally — empty state handles this gracefully
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (userId) fetchRecs(userId)
  }, [userId, fetchRecs])

  function handleBookLogged() {
    setBooksLogged(n => n + 1)
    if (userId) fetchRecs(userId)
  }

  return (
    <div className="min-h-screen bg-stone-50">
      <Header />

      <main className="max-w-2xl mx-auto px-4 py-8">

        {authError && (
          <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3 mb-6 text-sm text-red-700">
            Could not start a session — please check your connection and refresh the page.
          </div>
        )}

        {/* Need filter — lets users set mood and explicit interests */}
        {userId && (
          <NeedFilterPanel onApplied={() => fetchRecs(userId)} />
        )}

        {/* Inline book logger — always visible below the filter */}
        {userId && (
          <div className="mt-4">
            <InlineBookLogger userId={userId} onLogged={handleBookLogged} />
          </div>
        )}

        {/* Save profile nudge — appears after first book is logged */}
        {isAnonymous && booksLogged >= 1 && (
          <div className="flex items-center justify-between bg-amber-50 border border-amber-100 rounded-xl px-4 py-3 mt-4 text-sm">
            <span className="text-amber-800">Want these recommendations on any device?</span>
            <button
              onClick={() => setShowSaveModal(true)}
              className="text-amber-600 font-semibold hover:text-amber-700 transition ml-4 flex-shrink-0"
            >
              Save profile →
            </button>
          </div>
        )}

        {/* Recommendations section */}
        <div className="mt-8">
          <h2 className="font-serif text-2xl font-semibold text-gray-900 mb-1">For you</h2>
          <p className="text-sm text-gray-400 mb-6">Matched to your reading needs right now.</p>

          {loading && (
            <div className="flex flex-col gap-4">
              {[...Array(SKELETON_COUNT)].map((_, i) => (
                <div key={i} className="bg-white rounded-2xl h-36 animate-pulse border border-gray-100" />
              ))}
            </div>
          )}

          {!loading && books.length === 0 && (
            <div className="text-center py-16">
              <p className="text-3xl mb-4">📚</p>
              <p className="font-serif text-gray-700 text-lg mb-2">Log a book above to get started</p>
              <p className="text-gray-400 text-sm leading-relaxed">
                Your recommendations will appear here and update<br />each time you log a book you've read.
              </p>
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
        </div>
      </main>
      {showSaveModal && (
        <SaveProfileModal
          onClose={() => setShowSaveModal(false)}
          onSaved={() => {
            setIsAnonymous(false)
            setShowSaveModal(false)
          }}
        />
      )}
    </div>
  )
}
