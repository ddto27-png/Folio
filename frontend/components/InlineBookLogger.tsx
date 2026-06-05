'use client'

import { useState, useEffect, useRef } from 'react'
import Image from 'next/image'
import { searchBooks, findOrCreateBook, logRead, type BookSearchResult } from '@/lib/api'
import { EMOTIONAL_STATES } from '@/constants/emotional-states'

interface Props {
  userId: string
  onLogged: () => void   // called after a successful log — parent uses this to refresh recs
}

export function InlineBookLogger({ userId, onLogged }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<BookSearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [selected, setSelected] = useState<BookSearchResult | null>(null)
  const [rating, setRating] = useState<number | null>(null)
  const [feeling, setFeeling] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [justLogged, setJustLogged] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)

  // Debounced search — waits 300ms after typing stops before hitting the API
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

  // Close dropdown when clicking outside the search container
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
  }

  function reset() {
    setSelected(null)
    setQuery('')
    setResults([])
    setRating(null)
    setFeeling(null)
    setError('')
  }

  async function handleLog() {
    if (!selected || !rating || !feeling) return
    setSubmitting(true)
    setError('')
    try {
      // If the book came from Open Library (not yet in our catalog), create it first.
      // findOrCreateBook fetches the description and tags it with Claude Haiku.
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

      await logRead(userId, {
        book_id: bookId,
        signal_type: `star_${rating}`,
        pct_read: 1.0,
        emotional_state: feeling,
      })

      // Flash the "logged" confirmation, then reset the form
      setJustLogged(true)
      setTimeout(() => {
        setJustLogged(false)
        reset()
      }, 1500)
      onLogged()
    } catch {
      setError('Something went wrong. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  // Brief success state — shown for 1.5s after a book is logged
  if (justLogged) {
    return (
      <div className="bg-green-50 border border-green-100 rounded-2xl px-5 py-4 text-center">
        <p className="text-green-700 font-medium text-sm">✓ Logged! Updating your recommendations…</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Log a book</p>

      {/* Book search input with live dropdown */}
      <div ref={searchRef} className="relative">
        <input
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); setSelected(null) }}
          onFocus={() => results.length > 0 && setShowDropdown(true)}
          placeholder="Search by title…"
          className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
        />
        {searching && (
          <span className="absolute right-3 top-2.5 text-xs text-gray-400">Searching…</span>
        )}

        {/* Results dropdown — catalog results first, Open Library results labelled "+ Add" */}
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

      {/* Rating and mood — only visible after a book is selected */}
      {selected && (
        <div className="mt-4">
          <p className="text-xs font-medium text-gray-500 mb-2">How did you rate it?</p>
          <div className="flex gap-2 mb-4">
            {[1, 2, 3, 4, 5].map(n => (
              <button
                key={n}
                onClick={() => setRating(n)}
                className={`flex-1 py-2 rounded-xl text-lg transition ${
                  rating !== null && n <= rating
                    ? 'bg-amber-400 text-white'
                    : 'bg-gray-100 text-gray-400 hover:bg-amber-100'
                }`}
              >
                ★
              </button>
            ))}
          </div>

          <p className="text-xs font-medium text-gray-500 mb-2">How were you feeling when you read it?</p>
          <div className="flex flex-wrap gap-2 mb-4">
            {EMOTIONAL_STATES.map(s => (
              <button
                key={s.value}
                onClick={() => setFeeling(s.value)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${
                  feeling === s.value
                    ? 'bg-amber-500 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-amber-100'
                }`}
              >
                {s.chipLabel}
              </button>
            ))}
          </div>

          {error && <p className="text-red-500 text-sm mb-3">{error}</p>}

          <button
            onClick={handleLog}
            disabled={!rating || !feeling || submitting}
            className="w-full bg-amber-500 hover:bg-amber-600 text-white rounded-xl py-2.5 text-sm font-semibold transition disabled:opacity-40"
          >
            {submitting
              ? (selected && !selected.in_catalog ? 'Adding to catalog…' : 'Logging…')
              : 'Log this book'}
          </button>
        </div>
      )}
    </div>
  )
}
