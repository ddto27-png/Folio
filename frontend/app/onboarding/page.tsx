'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Image from 'next/image'
import { supabase } from '@/lib/supabase'
import { searchBooks, findOrCreateBook, logRead, type BookSearchResult } from '@/lib/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FEELINGS = [
  { label: 'In a dark place', value: 1 },
  { label: 'A bit low', value: 2 },
  { label: 'Just okay', value: 3 },
  { label: 'Pretty good', value: 4 },
  { label: 'Really happy', value: 5 },
]

const TIME_OPTIONS = [
  { label: 'This week', days: 4 },
  { label: 'This month', days: 20 },
  { label: 'A few months ago', days: 90 },
  { label: 'About a year ago', days: 365 },
  { label: 'A few years ago', days: 1000 },
  { label: 'More than 5 years ago', days: 2190 },
]

const SIGNAL_MAP: Record<number, string> = {
  1: 'star_1', 2: 'star_2', 3: 'star_3', 4: 'star_4', 5: 'star_5',
}

interface LoggedBook {
  bookId: string
  title: string
  coverUrl: string | null
  rating: number
  feeling: number
  daysAgo: number
}

// ---------------------------------------------------------------------------
// Onboarding page
// ---------------------------------------------------------------------------

export default function OnboardingPage() {
  const router = useRouter()
  const [userId, setUserId] = useState<string | null>(null)
  const [step, setStep] = useState<'welcome' | 'add' | 'done'>('welcome')
  const [loggedBooks, setLoggedBooks] = useState<LoggedBook[]>([])

  // Search state
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<BookSearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)

  // Current book being configured
  const [selected, setSelected] = useState<BookSearchResult | null>(null)
  const [rating, setRating] = useState<number | null>(null)
  const [feeling, setFeeling] = useState<number | null>(null)
  const [timeOption, setTimeOption] = useState<typeof TIME_OPTIONS[0] | null>(null)

  // Submission
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) { router.push('/'); return }
      setUserId(data.session.user.id)
    })
  }, [router])

  // Debounced search
  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); setShowDropdown(false); return }
    const timer = setTimeout(async () => {
      setSearching(true)
      const res = await searchBooks(query)
      setResults(res)
      setShowDropdown(true)
      setSearching(false)
    }, 300)
    return () => clearTimeout(timer)
  }, [query])

  // Close dropdown on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function handleSelectBook(book: BookSearchResult) {
    setSelected(book)
    setQuery(book.title)
    setShowDropdown(false)
    setRating(null)
    setFeeling(null)
    setTimeOption(null)
  }

  function resetForm() {
    setSelected(null)
    setQuery('')
    setResults([])
    setRating(null)
    setFeeling(null)
    setTimeOption(null)
    setError('')
  }

  const canAddBook = selected && rating && feeling && timeOption

  async function handleAddBook() {
    if (!canAddBook || !userId) return
    setSubmitting(true)
    setError('')

    try {
      // Ensure book is in catalog
      let bookId = selected.id
      if (!bookId) {
        const created = await findOrCreateBook({
          title: selected.title,
          author: selected.author,
          cover_url: selected.cover_url,
          pub_year: selected.pub_year,
          ol_key: selected.ol_key,
        })
        bookId = created.id
      }

      // Log the read
      const occurredAt = new Date(Date.now() - timeOption.days * 86400 * 1000).toISOString()
      await logRead(userId, {
        book_id: bookId,
        signal_type: SIGNAL_MAP[rating],
        pct_read: 1.0,
        emotional_state: feeling,
        occurred_at: occurredAt,
      })

      setLoggedBooks(prev => [...prev, {
        bookId,
        title: selected.title,
        coverUrl: selected.cover_url,
        rating,
        feeling,
        daysAgo: timeOption.days,
      }])
      resetForm()
    } catch {
      setError('Something went wrong. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleFinish() {
    router.push('/recommendations')
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (step === 'welcome') {
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div className="max-w-sm w-full text-center">
          <h1 className="font-serif text-4xl font-bold text-gray-900 mb-4">Welcome to Folio</h1>
          <p className="text-gray-500 text-sm leading-relaxed mb-2">
            Folio recommends books based on what you <em>need</em> right now — not what’s popular.
          </p>
          <p className="text-gray-500 text-sm leading-relaxed mb-10">
            To get started, tell us about a few books you’ve loved. The more you share, the better your recommendations.
          </p>
          <button
            onClick={() => setStep('add')}
            className="w-full bg-amber-500 hover:bg-amber-600 text-white rounded-2xl py-3.5 font-semibold text-sm transition"
          >
            Introduce us to your books →
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen px-4 py-10">
      <div className="max-w-lg mx-auto">

        {/* Header */}
        <div className="mb-8">
          <span className="font-serif font-bold text-gray-900 text-lg">Folio</span>
          <h2 className="font-serif text-2xl font-semibold text-gray-900 mt-4 mb-1">
            Introduce us to the books you’ve loved
          </h2>
          <p className="text-sm text-gray-400">
            Add at least one. Three or more gives you much better recommendations.
          </p>
        </div>

        {/* Already logged */}
        {loggedBooks.length > 0 && (
          <div className="flex flex-col gap-2 mb-6">
            {loggedBooks.map((b, i) => (
              <div key={i} className="bg-white rounded-xl border border-gray-100 px-4 py-3 flex items-center gap-3">
                {b.coverUrl ? (
                  <Image src={b.coverUrl} alt={b.title} width={32} height={48} className="rounded object-cover flex-shrink-0" unoptimized />
                ) : (
                  <div className="w-8 h-12 rounded bg-amber-50 flex items-center justify-center text-amber-300 flex-shrink-0 text-xs">📖</div>
                )}
                <div className="flex-1 min-w-0">
                  <p className="font-serif font-semibold text-gray-800 text-sm truncate">{b.title}</p>
                  <p className="text-xs text-gray-400">{'★'.repeat(b.rating)}{'☆'.repeat(5 - b.rating)}</p>
                </div>
                <span className="text-green-500 text-lg flex-shrink-0">✓</span>
              </div>
            ))}
          </div>
        )}

        {/* Book search */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {loggedBooks.length === 0 ? 'Search for a book you’ve read' : 'Add another book'}
          </label>

          <div ref={searchRef} className="relative mb-4">
            <input
              type="text"
              value={query}
              onChange={e => { setQuery(e.target.value); setSelected(null) }}
              onFocus={() => results.length > 0 && setShowDropdown(true)}
              placeholder="Type a title…"
              className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
            />
            {searching && (
              <span className="absolute right-3 top-2.5 text-xs text-gray-400">Searching…</span>
            )}

            {showDropdown && results.length > 0 && (
              <div className="absolute z-10 w-full mt-1 bg-white border border-gray-100 rounded-xl shadow-lg overflow-hidden max-h-64 overflow-y-auto">
                {results.map((book, i) => (
                  <button
                    key={i}
                    onClick={() => handleSelectBook(book)}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-amber-50 transition text-left"
                  >
                    {book.cover_url ? (
                      <Image src={book.cover_url} alt={book.title} width={28} height={40} className="rounded object-cover flex-shrink-0" unoptimized />
                    ) : (
                      <div className="w-7 h-10 rounded bg-gray-100 flex-shrink-0" />
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{book.title}</p>
                      {book.author && <p className="text-xs text-gray-400 truncate">{book.author}</p>}
                    </div>
                    {!book.in_catalog && (
                      <span className="ml-auto text-xs text-amber-500 flex-shrink-0">+ Add</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Rating */}
          {selected && (
            <>
              <label className="block text-sm font-medium text-gray-700 mb-2">How did you rate it?</label>
              <div className="flex gap-2 mb-4">
                {[1, 2, 3, 4, 5].map(n => (
                  <button
                    key={n}
                    onClick={() => setRating(n)}
                    className={`flex-1 py-2 rounded-xl text-lg transition ${rating !== null && n <= rating ? 'bg-amber-400 text-white' : 'bg-gray-100 text-gray-400 hover:bg-amber-100'}`}
                  >
                    ★
                  </button>
                ))}
              </div>

              {/* Feeling */}
              <label className="block text-sm font-medium text-gray-700 mb-2">How were you feeling when you read it?</label>
              <div className="flex flex-wrap gap-2 mb-4">
                {FEELINGS.map(f => (
                  <button
                    key={f.value}
                    onClick={() => setFeeling(f.value)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${feeling === f.value ? 'bg-amber-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-amber-100'}`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>

              {/* Time ago */}
              <label className="block text-sm font-medium text-gray-700 mb-2">How long ago did you read it?</label>
              <div className="flex flex-wrap gap-2">
                {TIME_OPTIONS.map(t => (
                  <button
                    key={t.days}
                    onClick={() => setTimeOption(t)}
                    className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${timeOption?.days === t.days ? 'bg-amber-500 text-white' : 'bg-gray-100 text-gray-600 hover:bg-amber-100'}`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

        {/* Actions */}
        <div className="flex flex-col gap-3">
          <button
            onClick={handleAddBook}
            disabled={!canAddBook || submitting}
            className="w-full bg-amber-500 hover:bg-amber-600 text-white rounded-2xl py-3 font-semibold text-sm transition disabled:opacity-40"
          >
            {submitting
              ? (selected && !selected.in_catalog ? 'Adding to catalog…' : 'Saving…')
              : loggedBooks.length === 0 ? 'Add this book' : 'Add another book'}
          </button>

          {loggedBooks.length > 0 && (
            <button
              onClick={handleFinish}
              className="w-full border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 rounded-2xl py-3 font-medium text-sm transition"
            >
              See my recommendations →
            </button>
          )}
        </div>

        {loggedBooks.length === 0 && (
          <button
            onClick={handleFinish}
            className="w-full mt-3 text-xs text-gray-400 hover:text-gray-600 transition"
          >
            Skip for now
          </button>
        )}
      </div>
    </div>
  )
}
