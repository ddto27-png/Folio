'use client'

import { useState } from 'react'
import { supabase } from '@/lib/supabase'

// Upgrades an anonymous Supabase session to a real account.
// All read events and recommendations are preserved — the user_id stays the same.
// Supabase handles the upgrade via updateUser(); no data migration needed.

interface Props {
  onClose: () => void
  onSaved: () => void   // called after successful upgrade — parent updates isAnonymous state
}

export function SaveProfileModal({ onClose, onSaved }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSave() {
    if (!email || !password) return
    setSaving(true)
    setError('')
    const { error } = await supabase.auth.updateUser({ email, password })
    if (error) {
      setError(error.message)
      setSaving(false)
    } else {
      onSaved()
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl max-w-sm w-full p-6 shadow-xl">
        <h2 className="font-serif text-xl font-semibold text-gray-900 mb-1">Save your profile</h2>
        <p className="text-sm text-gray-500 mb-6">
          Your logged books and recommendations will be accessible from any device.
          Nothing changes — we just attach an email to your existing session.
        </p>

        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-amber-400"
        />
        <input
          type="password"
          placeholder="Password (min 6 characters)"
          value={password}
          onChange={e => setPassword(e.target.value)}
          className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm mb-5 focus:outline-none focus:ring-2 focus:ring-amber-400"
        />

        {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 rounded-xl py-2.5 text-sm font-medium text-gray-600 hover:bg-gray-50 transition"
          >
            Not now
          </button>
          <button
            onClick={handleSave}
            disabled={!email || !password || saving}
            className="flex-1 bg-amber-500 hover:bg-amber-600 text-white rounded-xl py-2.5 text-sm font-semibold transition disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save profile'}
          </button>
        </div>
      </div>
    </div>
  )
}
