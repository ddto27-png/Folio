'use client'

import { useState } from 'react'
import { NEEDS } from '@/constants/needs'
import { EMOTIONAL_STATES } from '@/constants/emotional-states'
import { updateReadingState } from '@/lib/api'

interface Props {
  onApplied: () => void   // called after saving — parent re-fetches recommendations
}

export function NeedFilterPanel({ onApplied }: Props) {
  const [open, setOpen] = useState(false)
  const [emotionalState, setEmotionalState] = useState<number | null>(null)
  const [selectedNeeds, setSelectedNeeds] = useState<number[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  function toggleNeed(id: number) {
    setSelectedNeeds(prev =>
      prev.includes(id) ? prev.filter(n => n !== id) : [...prev, id]
    )
  }

  async function handleApply() {
    if (!emotionalState) return
    setSaving(true)
    setError('')
    try {
      await updateReadingState({ emotional_state: emotionalState, active_need_ids: selectedNeeds })
      setOpen(false)
      onApplied()
    } catch {
      setError('Something went wrong. Try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm">

      {/* Toggle header */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-4 text-left"
      >
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">What are you looking for?</p>
          {!open && (emotionalState || selectedNeeds.length > 0) && (
            <p className="text-sm text-gray-500 mt-0.5">
              {emotionalState ? EMOTIONAL_STATES.find(s => s.value === emotionalState)?.chipLabel : ''}
              {emotionalState && selectedNeeds.length > 0 ? ' · ' : ''}
              {selectedNeeds.length > 0 ? `${selectedNeeds.length} need${selectedNeeds.length > 1 ? 's' : ''} selected` : ''}
            </p>
          )}
          {!open && !emotionalState && selectedNeeds.length === 0 && (
            <p className="text-sm text-gray-400 mt-0.5">Set your mood and interests to personalise recommendations</p>
          )}
        </div>
        <span className="text-gray-400 text-lg ml-4">{open ? '↑' : '↓'}</span>
      </button>

      {open && (
        <div className="px-5 pb-5 border-t border-gray-50">

          {/* Emotional state */}
          <p className="text-xs font-medium text-gray-500 mt-4 mb-2">How are you feeling right now?</p>
          <div className="flex flex-wrap gap-2 mb-5">
            {EMOTIONAL_STATES.map(s => (
              <button
                key={s.value}
                onClick={() => setEmotionalState(s.value)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${
                  emotionalState === s.value
                    ? 'bg-amber-500 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-amber-100'
                }`}
              >
                {s.chipLabel}
              </button>
            ))}
          </div>

          {/* Need chips */}
          <p className="text-xs font-medium text-gray-500 mb-2">What themes are you drawn to? <span className="text-gray-400 font-normal">(optional)</span></p>
          <div className="flex flex-wrap gap-2 mb-5">
            {NEEDS.map(need => {
              const active = selectedNeeds.includes(need.id)
              return (
                <button
                  key={need.id}
                  onClick={() => toggleNeed(need.id)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition ${
                    active
                      ? 'bg-amber-500 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-amber-100'
                  }`}
                >
                  <span>{need.emoji}</span>
                  <span>{need.shortLabel}</span>
                </button>
              )
            })}
          </div>

          {error && <p className="text-red-500 text-sm mb-3">{error}</p>}

          <button
            onClick={handleApply}
            disabled={!emotionalState || saving}
            className="w-full bg-amber-500 hover:bg-amber-600 text-white rounded-xl py-2.5 text-sm font-semibold transition disabled:opacity-40"
          >
            {saving ? 'Saving…' : 'Update my recommendations'}
          </button>
        </div>
      )}
    </div>
  )
}
