// wishlist/page.tsx — shows the user's saved wishlist books ranked by match score.
//
// The wishlist is maintained by the Supabase backend: every time the user logs
// a read, a DB trigger recomputes which wishlist books match them best and
// updates the rank column. This page just reads and displays that pre-ranked list.
//
// Each row shows: rank number, cover image, title, author, need badges, and match %.

'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { getWishlist, type WishlistItem } from '@/lib/api'
import { NeedBadge } from '@/components/NeedBadge'
import { Header } from '@/components/Header'
import Image from 'next/image'

export default function WishlistPage() {
  const router = useRouter()
  const [books, setBooks] = useState<WishlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // On mount: verify session and load the wishlist from the backend.
  useEffect(() => {
    supabase.auth.getSession().then(async ({ data }) => {
      if (!data.session) { router.push('/'); return }
      try {
        const items = await getWishlist(data.session.user.id)
        setBooks(items)
      } catch {
        setError('Could not load wishlist.')
      } finally {
        setLoading(false)
      }
    })
  }, [router])

  return (
    <>
      <Header />
      <main className="max-w-2xl mx-auto px-4 py-8">
        <h2 className="font-serif text-2xl font-semibold text-gray-900 mb-1">Wishlist</h2>
        <p className="text-sm text-gray-400 mb-6">Ranked by how well they match you right now.</p>

        {/* Skeleton loading state while the wishlist loads */}
        {loading && (
          <div className="flex flex-col gap-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="bg-white rounded-2xl h-24 animate-pulse border border-gray-100" />
            ))}
          </div>
        )}

        {error && <div className="bg-red-50 text-red-700 rounded-xl p-4 text-sm">{error}</div>}

        {/* Empty state — shown if the user hasn't saved any books yet */}
        {!loading && !error && books.length === 0 && (
          <div className="text-center py-16">
            <p className="text-gray-400 text-sm">Your wishlist is empty.</p>
            <p className="text-gray-400 text-sm mt-1">Books you save will appear here, ranked by match score.</p>
          </div>
        )}

        {/* Wishlist rows — numbered list sorted by rank (rank 1 = best match) */}
        <div className="flex flex-col gap-3">
          {books.map((book, i) => (
            <div key={book.book_id} className="bg-white rounded-2xl border border-gray-100 p-4 flex gap-3 items-center shadow-sm">
              {/* Rank number — comes from the wishlist.rank column, maintained by the DB trigger */}
              <span className="text-sm font-bold text-gray-300 w-6 text-center flex-shrink-0">{i + 1}</span>

              {/* Cover image, or amber placeholder if no cover is available */}
              {book.cover_url ? (
                <Image
                  src={book.cover_url}
                  alt={book.title}
                  width={44}
                  height={64}
                  className="rounded object-cover shadow-sm flex-shrink-0"
                  unoptimized
                />
              ) : (
                <div className="w-11 h-16 rounded bg-amber-50 flex items-center justify-center text-amber-300 flex-shrink-0">📖</div>
              )}

              <div className="flex-1 min-w-0">
                <p className="font-serif font-semibold text-gray-900 leading-snug truncate">{book.title}</p>
                {book.author && <p className="text-xs text-gray-400 mb-1.5">{book.author}</p>}
                {/* NeedBadges show which psychological needs this book matched for the user */}
                <div className="flex flex-wrap gap-1">
                  {(book.need_ids_matched ?? []).map(id => <NeedBadge key={id} needId={id} />)}
                </div>
              </div>

              {/* Match score percentage — how well this book fits the user right now */}
              {book.match_score != null && (
                <span className="flex-shrink-0 text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
                  {Math.round(book.match_score * 100)}%
                </span>
              )}
            </div>
          ))}
        </div>
      </main>
    </>
  )
}
