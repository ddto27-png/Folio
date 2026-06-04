// LogReadModal.tsx — a full-screen overlay modal for logging a read event.
//
// Opened when the user clicks "I've read this" on a BookCard in the recommendations list.
// Collects three pieces of information:
//   1. Signal type (star rating or abandoned/re-read) → maps to SIGNAL_WEIGHTS in scoring.py
//   2. Percentage read → affects how much credibility the signal carries (finish_multiplier)
//   3. Emotional state when reading → amplifies certain psychological needs (emotional_alignment)
//
// After saving, the parent page (recommendations) refreshes its list via onSaved callback.

'use client'

import { useState } from 'react'
import { logRead } from '@/lib/api'

// Signal options presented in the dropdown — these values match the keys in
// SIGNAL_WEIGHTS in scoring.py. The score they carry ranges from +1.0 (loved it)
// to -0.8 (disliked it), with re_read as a special strong-positive signal.
const SIGNALS = [
  { value: 'star_5', label: '★★★★★  Loved it' },
  { value: 'star_4', label: '★★★★  Really liked it' },
  { value: 'star_3', label: '★★★  It was okay' },
  { value: 'star_2', label: '★★  Didn\'t like it' },
  { value: 'star_1', label: '★  Disliked it' },
  { value: 'abandoned', label: '✕  Abandoned' },
  { value: 're_read', label: '↩  Re-read' },
]

// Emotional state options — the 1–5 scale used throughout the scoring engine.
// State 1 (crisis) boosts needs like wound_visible and surviving;
// State 5 (thriving) boosts being_chosen and creative_kinship.
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
  onClose: () => void    // called when the user clicks Cancel
  onSaved: () => void    // called after a successful save (refreshes recommendations)
}

export function LogReadModal({ bookId, bookTitle, userId, onClose, onSaved }: Props) {
  // Default values make it easy to save quickly — most users finished and loved the book
  const [signal, setSignal] = useState('star_5')
  const [pctRead, setPctRead] = useState(100)        // 0–100 slider, converted to 0–1 on submit
  const [state, setState] = useState(3)              // neutral default
  const [postState, setPostState] = useState<number | null>(null)  // optional — how they felt after
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Submits the read event to POST /users/{user_id}/reads.
  // The backend trigger then recomputes the user's need affinities automatically.
  // occurred_at is not set here — it defaults to "now" on the backend.
  async function handleSave() {
    setSaving(true)
    setError('')
    try {
      await logRead(userId, {
        book_id: bookId,
        signal_type: signal,
        pct_read: pctRead / 100,  // convert percentage to 0–1 float
        emotional_state: state,
        ...(postState !== null && { post_emotional_state: postState }),
      })
      onSaved()
    } catch {
      setError('Something went wrong. Try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    // Semi-transparent dark overlay behind the modal
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl">
        <h2 className="font-serif text-xl font-semibold text-gray-900 mb-1">Log this read</h2>
        <p className="text-sm text-gray-500 mb-6 truncate">{bookTitle}</p>

        {/* Signal selector — how the user felt about the book overall */}
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

        {/* Percentage read slider — shown as a live number next to the label.
            Feeds finish_multiplier() in scoring.py: <50% = 0.3×, 50–90% = 0.6×, ≥90% = 1.0× */}
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

        {/* Emotional state selector — feeds emotional_alignment() in scoring.py */}
        <label className="block text-sm font-medium text-gray-700 mb-1">How were you feeling when you read it?</label>
        <select
          value={state}
          onChange={e => setState(Number(e.target.value))}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-amber-400"
        >
          {STATES.map(s => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>

        {/* Post-read state chips — optional. The before/after delta lets the engine
            learn whether this reader uses books as a mirror or an escape. Skippable
            because readers may not remember or may not want to reflect on it. */}
        <label className="block text-sm font-medium text-gray-700 mb-2">
          How did you feel after finishing?{' '}
          <span className="text-gray-400 font-normal">(optional)</span>
        </label>
        <div className="flex gap-2 mb-6">
          {STATES.map(s => (
            <button
              key={s.value}
              type="button"
              onClick={() => setPostState(postState === s.value ? null : s.value)}
              className={`flex-1 py-1.5 rounded-lg text-xs font-medium border transition ${
                postState === s.value
                  ? 'bg-amber-500 border-amber-500 text-white'
                  : 'border-gray-200 text-gray-500 hover:border-amber-300 hover:text-gray-700'
              }`}
            >
              {s.value}
            </button>
          ))}
        </div>

        {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

        {/* Cancel / Save buttons */}
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
