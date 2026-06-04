// BookCard.tsx — displays a single recommended book on the "For you" page.
//
// Shows:
//   - Cover image (or amber placeholder if no image)
//   - Title + author
//   - Match score percentage (the output of the scoring engine, 0–100%)
//   - why_text: a Claude-generated 2-sentence explanation of why this book fits
//   - NeedBadges: coloured chips for the 1–2 psychological needs driving the match
//   - "I've read this" button: opens LogReadModal so the user can log the read
//
// When the user saves a read via LogReadModal, onReadLogged is called to
// refresh the recommendation list on the parent page.

'use client'

import Image from 'next/image'
import { useState } from 'react'
import { NeedBadge } from './NeedBadge'
import { LogReadModal } from './LogReadModal'

interface Props {
  bookId: string
  title: string
  author: string | null
  coverUrl: string | null
  matchScore: number         // 0–1 float from the scoring engine
  topNeedIds: number[]       // 1–2 need IDs (integers from the DB 'needs' table)
  whyText: string            // Claude-generated personalised explanation
  userId: string
  onReadLogged?: () => void  // callback to refresh recommendations after logging
}

export function BookCard({ bookId, title, author, coverUrl, matchScore, topNeedIds, whyText, userId, onReadLogged }: Props) {
  const [showModal, setShowModal] = useState(false)  // controls LogReadModal visibility
  const pct = Math.round(matchScore * 100)           // convert 0–1 to display percentage

  return (
    <>
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 flex gap-4 hover:shadow-md transition">

        {/* Book cover — uses Open Library cover URL; falls back to an amber placeholder */}
        <div className="flex-shrink-0">
          {coverUrl ? (
            <Image
              src={coverUrl}
              alt={title}
              width={72}
              height={108}
              className="rounded-lg object-cover shadow-sm"
              unoptimized  // skip Next.js image optimisation since covers come from an external CDN
            />
          ) : (
            <div className="w-[72px] h-[108px] rounded-lg bg-amber-50 flex items-center justify-center text-amber-300 text-2xl">
              📖
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          {/* Title row with match score badge in the top-right corner */}
          <div className="flex items-start justify-between gap-2 mb-0.5">
            <h3 className="font-serif font-semibold text-gray-900 leading-snug">{title}</h3>
            <span className="flex-shrink-0 text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
              {pct}%
            </span>
          </div>

          {author && <p className="text-sm text-gray-400 mb-2">{author}</p>}

          {/* why_text: the personalised explanation from Claude — displayed as an italic quote */}
          <p className="text-sm text-gray-600 italic leading-relaxed mb-3">"{whyText}"</p>

          {/* NeedBadges: coloured chips showing which psychological needs this book serves */}
          <div className="flex flex-wrap gap-1.5 mb-3">
            {topNeedIds.map(id => <NeedBadge key={id} needId={id} />)}
          </div>

          {/* Opens LogReadModal so the user can rate this book and log it to their profile */}
          <button
            onClick={() => setShowModal(true)}
            className="text-xs font-medium text-gray-400 hover:text-amber-600 transition"
          >
            + I've read this
          </button>
        </div>
      </div>

      {/* LogReadModal is rendered as a portal overlay; only mounted when showModal=true */}
      {showModal && (
        <LogReadModal
          bookId={bookId}
          bookTitle={title}
          userId={userId}
          onClose={() => setShowModal(false)}
          onSaved={() => { setShowModal(false); onReadLogged?.() }}
        />
      )}
    </>
  )
}
