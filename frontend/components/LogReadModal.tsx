'use client'

import { useState } from 'react'
import { logRead } from '@/lib/api'

const SIGNALS = [
  { value: 'star_5', label: '★★★★★  Loved it' },
  { value: 'star_4', label: '★★★★  Really liked it' },
  { value: 'star_3', label: '★★★  It was okay' },
  { value: 'star_2', label: '★★  Didn\'t like it' },
  { value: 'star_1', label: '★  Disliked it' },
  { value: 'abandoned', label: '✕  Abandoned' },
  { value: 're_read', label: '↩  Re-read' },
]

const STATES = [
  { value: 1, label: '1 — In crisis' },
  { value: 2, label: '2 — Struggling' },
  { value: 3, label: '3 — Neutral' },
  { value: 4, label: '4 — Doing well' },
  { value: 5, label: '5 — Thriving' },
]

interface Props {
  bookId: string
  bookTitle: string
  userId: string
  onClose: () => void
  onSaved: () => void
}

export function LogReadModal({ bookId, bookTitle, userId, onClose, onSaved }: Props) {
  const [signal, setSignal] = useState('star_5')
  const [pctRead, setPctRead] = useState(100)
  const [state, setState] = useState(3)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSave() {
    setSaving(true)
    setError('')
    try {
      await logRead(userId, {
        book_id: bookId,
        signal_type: signal,
        pct_read: pctRead / 100,
        emotional_state: state,
      })
      onSaved()
    } catch {
      setError('Something went wrong. Try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl">
        <h2 className="font-serif text-xl font-semibold text-gray-900 mb-1">Log this read</h2>
        <p className="text-sm text-gray-500 mb-6 truncate">{bookTitle}</p>

        <label className="block text-sm font-medium text-gray-700 mb-1">How did you feel about it?</label>
        <select
          value={signal}
          onChange={e => setSignal(e.target.value)}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-amber-400"
        >
          {SIGNALS.map(s => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>

        <label className="block text-sm font-medium text-gray-700 mb-1">
          How much did you read? <span className="text-amber-600 font-semibold">{pctRead}%</span>
        </label>
        <input
          type="range"
          min={0}
          max={100}
          value={pctRead}
          onChange={e => setPctRead(Number(e.target.value))}
          className="w-full accent-amber-500 mb-4"
        />

        <label className="block text-sm font-medium text-gray-700 mb-1">How were you feeling when you read it?</label>
        <select
          value={state}
          onChange={e => setState(Number(e.target.value))}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm mb-6 focus:outline-none focus:ring-2 focus:ring-amber-400"
        >
          {STATES.map(s => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>

        {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 rounded-xl py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50 transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 bg-amber-500 hover:bg-amber-600 text-white rounded-xl py-2.5 text-sm font-semibold transition disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
