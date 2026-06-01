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
  matchScore: number
  topNeedIds: number[]
  whyText: string
  userId: string
  onReadLogged?: () => void
}

export function BookCard({ bookId, title, author, coverUrl, matchScore, topNeedIds, whyText, userId, onReadLogged }: Props) {
  const [showModal, setShowModal] = useState(false)
  const pct = Math.round(matchScore * 100)

  return (
    <>
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 flex gap-4 hover:shadow-md transition">
        <div className="flex-shrink-0">
          {coverUrl ? (
            <Image
              src={coverUrl}
              alt={title}
              width={72}
              height={108}
              className="rounded-lg object-cover shadow-sm"
              unoptimized
            />
          ) : (
            <div className="w-[72px] h-[108px] rounded-lg bg-amber-50 flex items-center justify-center text-amber-300 text-2xl">
              📖
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 mb-0.5">
            <h3 className="font-serif font-semibold text-gray-900 leading-snug">{title}</h3>
            <span className="flex-shrink-0 text-xs font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
              {pct}%
            </span>
          </div>
          {author && <p className="text-sm text-gray-400 mb-2">{author}</p>}

          <p className="text-sm text-gray-600 italic leading-relaxed mb-3">"{whyText}"</p>

          <div className="flex flex-wrap gap-1.5 mb-3">
            {topNeedIds.map(id => <NeedBadge key={id} needId={id} />)}
          </div>

          <button
            onClick={() => setShowModal(true)}
            className="text-xs font-medium text-gray-400 hover:text-amber-600 transition"
          >
            + I've read this
          </button>
        </div>
      </div>

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
