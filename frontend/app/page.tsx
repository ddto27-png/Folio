'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'

async function getRedirectPath(userId: string): Promise<string> {
  const { data } = await supabase
    .from('reads')
    .select('id', { count: 'exact', head: true })
    .eq('user_id', userId)
  return (data as unknown as { count: number } | null)?.count === 0 || data === null
    ? '/onboarding'
    : '/recommendations'
}

export default function Home() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSignUp, setIsSignUp] = useState(false)
  const [loading, setLoading] = useState(false)
  const [guestLoading, setGuestLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data }) => {
      if (data.session) {
        const path = await getRedirectPath(data.session.user.id)
        router.push(path)
      }
    })
  }, [router])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')

    const { data, error } = isSignUp
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password })

    if (error) {
      setError(error.message)
      setLoading(false)
    } else if (data.user) {
      const path = await getRedirectPath(data.user.id)
      router.push(path)
    }
  }

  async function handleGuest() {
    setGuestLoading(true)
    setError('')
    const { data, error } = await supabase.auth.signInAnonymously()
    if (error) {
      setError(error.message)
      setGuestLoading(false)
    } else if (data.user) {
      router.push('/onboarding')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="font-serif text-4xl font-bold text-gray-900 mb-2 text-center">Folio</h1>
        <p className="text-center text-gray-500 text-sm mb-10">Books that meet you where you are.</p>

        <form onSubmit={handleSubmit} className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6 flex flex-col gap-4">
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            className="border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            className="border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
          {error && <p className="text-red-500 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="bg-amber-500 hover:bg-amber-600 text-white rounded-xl py-3 font-semibold text-sm transition disabled:opacity-50"
          >
            {loading ? 'Loading…' : isSignUp ? 'Create account' : 'Sign in'}
          </button>
          <button
            type="button"
            onClick={() => setIsSignUp(!isSignUp)}
            className="text-sm text-gray-400 hover:text-gray-600 transition text-center"
          >
            {isSignUp ? 'Already have an account? Sign in' : "Don't have an account? Sign up"}
          </button>
        </form>

        <div className="flex items-center gap-3 my-5">
          <div className="flex-1 h-px bg-gray-200" />
          <span className="text-xs text-gray-400">or</span>
          <div className="flex-1 h-px bg-gray-200" />
        </div>

        <button
          onClick={handleGuest}
          disabled={guestLoading}
          className="w-full border border-gray-200 bg-white hover:bg-gray-50 text-gray-600 rounded-2xl py-3 text-sm font-medium transition disabled:opacity-50"
        >
          {guestLoading ? 'Loading…' : 'Continue as guest'}
        </button>
        <p className="text-center text-xs text-gray-400 mt-3">No account needed. Your reads are saved locally.</p>
      </div>
    </div>
  )
}
