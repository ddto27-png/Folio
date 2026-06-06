// NavBar.tsx — sticky top navigation bar shown on all post-login pages.
//
// Contains:
//   - "Folio" brand name (left)
//   - "For you" link → /recommendations
//   - "Wishlist" link → /wishlist
//   - "Sign out" button (clears the Supabase session and redirects to "/")
//
// The active link is highlighted in amber based on the current pathname.
// The bar is semi-transparent with a blur effect (bg-white/90 backdrop-blur)
// so content scrolls underneath it naturally.

'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { useRouter } from 'next/navigation'

export function NavBar() {
  const pathname = usePathname()  // used to highlight the active nav link
  const router = useRouter()

  // Signs the user out of Supabase and redirects them to the login page.
  // Works for both email/password accounts and anonymous (guest) sessions.
  async function handleSignOut() {
    await supabase.auth.signOut()
    router.push('/')
  }

  return (
    <nav className="sticky top-0 z-40 bg-white/90 backdrop-blur border-b border-gray-100">
      <div className="max-w-2xl mx-auto px-4 h-14 flex items-center justify-between">
        <span className="font-serif font-bold text-gray-900 text-lg tracking-tight">Folio</span>
        <div className="flex items-center gap-6">
          {/* "For you" — highlighted amber when on the recommendations page */}
          <Link
            href="/"
            className={`text-sm font-medium transition ${pathname === '/' ? 'text-amber-600' : 'text-gray-500 hover:text-gray-800'}`}
          >
            For you
          </Link>
          {/* "Wishlist" — highlighted amber when on the wishlist page */}
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
