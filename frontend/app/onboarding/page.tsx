// onboarding/page.tsx — the onboarding flow for new users.
//
// Purpose: new users arrive here with zero read history, so the scoring engine
// has nothing to work with. This page lets them log a handful of books they've
// already read (with ratings, mood, and time ago) to seed their psychological
// profile before they see their first recommendations.
//
// Flow:
//   Step 1 "welcome"  — brief intro screen explaining what Folio does
//   Step 2 "add"      — search for books, rate them, log them one by one
//   (done)            — "See my recommendations →" navigates to /recommendations
//
// When the user picks a book that isn't in our catalog yet (in_catalog=false,
// comes from Open Library), we call findOrCreateBook first to add it to the DB
// and tag it with Claude Haiku before logging the read.

'use client'

import { useEffect, useState, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Image from 'next/image'
import { supabase } from '@/lib/supabase'
import { searchBooks, findOrCreateBook, logRead, type BookSearchResult } from '@/lib/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// The emotional state options shown as chips after a book is selected.
// Values 1–5 match the emotional_state scale used throughout the scoring engine.
const FEELINGS = [
  { label: 'In a dark place', value: 1 },
  { label: 'A bit low', value: 2 },
  { label: 'Just okay', value: 3 },
  { label: 'Pretty good', value: 4 },
  { label: 'Really happy', value: 5 },
]

// How long ago the user read the book. Converts to days so we can backdate
// the occurred_at timestamp when logging the read, which feeds the scoring
// engine's exponential decay (older reads count for less).
const TIME_OPTIONS = [
  { label: 'This week', days: 4 },
  { label: 'This month', days: 20 },
  { label: 'A few months ago', days: 90 },
  { label: 'About a year ago', days: 365 },
  { label: 'A few years ago', days: 1000 },
  { label: 'More than 5 years ago', days: 2190 },
]

// Maps 1–5 star rating to the signal_type strings used in SIGNAL_WEIGHTS
// in scoring.py. These drive how strongly a book influences the user's
// affinity profile for each psychological need.
const SIGNAL_MAP: Record<number, string> = {
  1: 'star_1', 2: 'star_2', 3: 'star_3', 4: 'star_4', 5: 'star_5',
}

// Shape of a book after it's been successfully logged during onboarding.
// Used to display the accumulating list of logged books at the top of the form.
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
  const [loggedBooks, setLoggedBooks] = useState<LoggedBook[]>([])  // books logged so far this session

  // Search input state
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<BookSearchResult[]>([])  // search results from the API
  const [searching, setSearching] = useState(false)               // shows "Searching…" indicator
  const [showDropdown, setShowDropdown] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)  // used to detect clicks outside the dropdown

  // The book the user has selected from the dropdown
  const [selected, setSelected] = useState<BookSearchResult | null>(null)
  // The three pieces of metadata collected after a book is selected
  const [rating, setRating] = useState<number | null>(null)
  const [feeling, setFeeling] = useState<number | null>(null)
  const [timeOption, setTimeOption] = useState<typeof TIME_OPTIONS[0] | null>(null)

  // Form submission state
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  // On mount: verify the user is logged in. If not, send them to the login page.
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) { router.push('/'); return }
      setUserId(data.session.user.id)
    })
  }, [router])

  // Debounced search: waits 300ms after the user stops typing before hitting the API.
  // This avoids making a request for every keystroke.
  useEffect(() => {
    if (query.trim().length < 2) { setResults([]); setShowDropdown(false); return }
    const timer = setTimeout(async () => {
      setSearching(true)
      const res = await searchBooks(query)
      setResults(res)
      setShowDropdown(true)
      setSearching(false)
    }, 300)
    return () => clearTimeout(timer)  // cancel the previous timer if the user keeps typing
  }, [query])

  // Close the search dropdown when the user clicks anywhere outside the search box.
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Called when the user clicks a book in the dropdown.
  // Fills the search input with the book title and resets the rating/feeling/time fields.
  function handleSelectBook(book: BookSearchResult) {
    setSelected(book)
    setQuery(book.title)
    setShowDropdown(false)
    setRating(null)
    setFeeling(null)
    setTimeOption(null)
  }

  // Clears all form fields so the user can add another book.
  function resetForm() {
    setSelected(null)
    setQuery('')
    setResults([])
    setRating(null)
    setFeeling(null)
    setTimeOption(null)
    setError('')
  }

  // The "Add this book" button is only active when all four fields are filled in.
  const canAddBook = selected && rating && feeling && timeOption

  // Main submission handler — logs the book to the backend.
  //
  // If the book isn't in our catalog yet (selected from Open Library, id=null),
  // we first call findOrCreateBook which fetches its description, inserts it,
  // and tags it with Claude Haiku. Then we log the read with:
  //   - a backdated occurred_at (timeOption.days ago) so scoring weights recency correctly
  //   - the star rating mapped to a signal_type string
  //   - the feeling value (1–5) as the emotional_state
  async function handleAddBook() {
    if (!canAddBook || !userId) return
    setSubmitting(true)
    setError('')

    try {
      // If book isn't in our catalog, add it first
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

      // Backdate the read by however many days the user indicated
      const occurredAt = new Date(Date.now() - timeOption.days * 86400 * 1000).toISOString()
      await logRead(userId, {
        book_id: bookId,
        signal_type: SIGNAL_MAP[rating],   // e.g. "star_4"
        pct_read: 1.0,                      // assume finished during onboarding
        emotional_state: feeling,
        occurred_at: occurredAt,
      })

      // Add the book to the "already logged" list shown at the top of the page
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

  // Navigates to recommendations once the user is done adding books.
  async function handleFinish() {
    router.push('/recommendations')
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // Welcome screen shown first — brief pitch and a single CTA button.
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

        {/* Page header */}
        <div className="mb-8">
          <span className="font-serif font-bold text-gray-900 text-lg">Folio</span>
          <h2 className="font-serif text-2xl font-semibold text-gray-900 mt-4 mb-1">
            Introduce us to the books you’ve loved
          </h2>
          <p className="text-sm text-gray-400">
            Add at least one. Three or more gives you much better recommendations.
          </p>
        </div>

        {/* List of books already logged this session — shown above the form */}
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
                  {/* Star rating display using filled (★) and empty (☆) stars */}
                  <p className="text-xs text-gray-400">{'★'.repeat(b.rating)}{'☆'.repeat(5 - b.rating)}</p>
                </div>
                <span className="text-green-500 text-lg flex-shrink-0">✓</span>
              </div>
            ))}
          </div>
        )}

        {/* Main book entry form */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {loggedBooks.length === 0 ? 'Search for a book you’ve read' : 'Add another book'}
          </label>

          {/* Search input with debounced dropdown */}
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

            {/* Dropdown: shows search results from catalog + Open Library.
                Books with in_catalog=false show a "+ Add" badge indicating
                they'll be created in the DB when selected. */}
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
                    {/* Badge shown for Open Library books not yet in our catalog */}
                    {!book.in_catalog && (
                      <span className="ml-auto text-xs text-amber-500 flex-shrink-0">+ Add</span>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Rating, feeling, and time fields — only shown after a book is selected */}
          {selected && (
            <>
              {/* Star rating: clicking star N fills stars 1–N (cumulative highlight) */}
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

              {/* Emotional state when the book was read — feeds emotional_state in the read event */}
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

              {/* How long ago — used to backdate occurred_at for the decay calculation */}
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

        {/* Action buttons */}
        <div className="flex flex-col gap-3">
          {/* Primary CTA — disabled until all four fields are filled.
              Shows "Adding to catalog…" if the book needs to be created first. */}
          <button
            onClick={handleAddBook}
            disabled={!canAddBook || submitting}
            className="w-full bg-amber-500 hover:bg-amber-600 text-white rounded-2xl py-3 font-semibold text-sm transition disabled:opacity-40"
          >
            {submitting
              ? (selected && !selected.in_catalog ? 'Adding to catalog…' : 'Saving…')
              : loggedBooks.length === 0 ? 'Add this book' : 'Add another book'}
          </button>

          {/* "See my recommendations" appears after the first book is logged */}
          {loggedBooks.length > 0 && (
            <button
              onClick={handleFinish}
              className="w-full border border-gray-200 bg-white hover:bg-gray-50 text-gray-700 rounded-2xl py-3 font-medium text-sm transition"
            >
              See my recommendations →
            </button>
          )}
        </div>

        {/* Subtle skip link — lets the user skip onboarding entirely.
            They'll see recommendations with equal scores until they log some reads. */}
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
