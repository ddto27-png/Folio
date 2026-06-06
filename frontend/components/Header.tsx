'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { supabase } from '@/lib/supabase'
import { SaveProfileModal } from '@/components/SaveProfileModal'

function NavLink({ href, label }: { href: string; label: string }) {
  const pathname = usePathname()
  return (
    <Link
      href={href}
      className={`text-sm font-medium transition ${pathname === href ? 'text-amber-600' : 'text-gray-500 hover:text-gray-800'}`}
    >
      {label}
    </Link>
  )
}

export function Header() {
  const router = useRouter()
  const [isAnonymous, setIsAnonymous] = useState(true)
  const [showSaveModal, setShowSaveModal] = useState(false)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setIsAnonymous(data.session?.user.is_anonymous ?? true)
    })
  }, [])

  async function handleSignOut() {
    await supabase.auth.signOut()
    router.push('/')
  }

  return (
    <>
      <header className="sticky top-0 z-40 bg-white/90 backdrop-blur border-b border-gray-100">
        <div className="max-w-2xl mx-auto px-4 h-14 flex items-center justify-between">
          <span className="font-serif font-bold text-gray-900 text-lg tracking-tight">Folio</span>
          <div className="flex items-center gap-6">
            <NavLink href="/" label="For you" />
            <NavLink href="/wishlist" label="Wishlist" />
            {isAnonymous ? (
              <button
                onClick={() => setShowSaveModal(true)}
                className="text-sm text-amber-600 font-medium hover:text-amber-700 transition"
              >
                Save profile
              </button>
            ) : (
              <>
                <span className="text-sm text-gray-400">✓ Profile saved</span>
                <button
                  onClick={handleSignOut}
                  className="text-sm text-gray-400 hover:text-gray-600 transition"
                >
                  Sign out
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {showSaveModal && (
        <SaveProfileModal
          onClose={() => setShowSaveModal(false)}
          onSaved={() => {
            setIsAnonymous(false)
            setShowSaveModal(false)
          }}
        />
      )}
    </>
  )
}
