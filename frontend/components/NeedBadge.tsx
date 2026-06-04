// NeedBadge.tsx — a small coloured chip that labels one psychological need.
//
// Used in BookCard (recommendations) and WishlistPage to show which of the
// 13 needs a book serves. Each need has a distinct colour so users can
// recognise patterns across their recommendations at a glance.
//
// needId is the integer primary key from the Supabase 'needs' table,
// which matches the NEED_CODE_TO_ID mapping in main.py.

// Short display labels for each of the 13 psychological needs.
// These are abbreviated versions of the full need descriptions in scoring.py.
const NEED_LABELS: Record<number, string> = {
  1: 'Being chosen',   // being_chosen
  2: 'Surviving',      // surviving
  3: 'Closure',        // procedural_resolution
  4: 'Moral grey',     // moral_complexity
  5: 'Power',          // power_agency
  6: 'Wound visible',  // wound_visible
  7: 'History',        // making_sense_history
  8: 'Reinvention',    // self_remade
  9: 'Inside power',   // inside_power
  10: 'Being seen',    // identity_witnessed
  11: 'Wonder',        // world_larger
  12: 'Creative bond', // creative_kinship
  13: 'Anxiety held',  // anxiety_named
}

// Distinct Tailwind colour class pairs for each need — background + text.
// Needs that are conceptually darker (grief, survival) use warmer/deeper colours;
// lighter needs (wonder, love) use cooler/softer ones.
const NEED_COLORS: Record<number, string> = {
  1:  'bg-rose-100 text-rose-700',
  2:  'bg-red-100 text-red-800',
  3:  'bg-blue-100 text-blue-700',
  4:  'bg-purple-100 text-purple-700',
  5:  'bg-orange-100 text-orange-700',
  6:  'bg-pink-100 text-pink-800',
  7:  'bg-green-100 text-green-700',
  8:  'bg-teal-100 text-teal-700',
  9:  'bg-amber-100 text-amber-800',
  10: 'bg-violet-100 text-violet-700',
  11: 'bg-sky-100 text-sky-700',
  12: 'bg-indigo-100 text-indigo-700',
  13: 'bg-slate-100 text-slate-700',
}

// Renders a single pill-shaped badge for a given need ID.
// Falls back to a neutral grey style if the ID is unknown.
export function NeedBadge({ needId }: { needId: number }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${NEED_COLORS[needId] ?? 'bg-gray-100 text-gray-600'}`}>
      {NEED_LABELS[needId] ?? `Need ${needId}`}
    </span>
  )
}
