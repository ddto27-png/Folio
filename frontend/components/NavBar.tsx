'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { useRouter } from 'next/navigation'

export function NavBar() {
  const pathname = usePathname()
  const router = useRouter()

  async function handleSignOut() {
    await supabase.auth.signOut()
    router.push('/')
  }

  return (
    <nav className="sticky top-0 z-40 bg-white/90 backdrop-blur border-b border-gray-100">
      <div className="max-w-2xl mx-auto px-4 h-14 flex items-center justify-between">
        <span className="font-serif font-bold text-gray-900 text-lg tracking-tight">Folio</span>
        <div className="flex items-center gap-6">
          <Link
            href="/recommendations"
            className={`text-sm font-medium transition ${pathname === '/recommendations' ? 'text-amber-600' : 'text-gray-500 hover:text-gray-800'}`}
          >
            For you
          </Link>
          <Link
            href="/wishlist"
            className={`text-sm font-medium transition ${pathname === '/wishlist' ? 'text-amber-600' : 'text-gray-500 hover:text-gray-800'}`}
          >
            Wishlist
          </Link>
          <button
            onClick={handleSignOut}
            className="text-sm text-gray-400 hover:text-gray-600 transition"
          >
            Sign out
          </button>
        </div>
      </div>
    </nav>
  )
}
