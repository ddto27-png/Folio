const NEED_LABELS: Record<number, string> = {
  1: 'Being chosen',
  2: 'Surviving',
  3: 'Closure',
  4: 'Moral grey',
  5: 'Power',
  6: 'Wound visible',
  7: 'History',
  8: 'Reinvention',
  9: 'Inside power',
  10: 'Being seen',
  11: 'Wonder',
  12: 'Creative bond',
  13: 'Anxiety held',
}

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

export function NeedBadge({ needId }: { needId: number }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${NEED_COLORS[needId] ?? 'bg-gray-100 text-gray-600'}`}>
      {NEED_LABELS[needId] ?? `Need ${needId}`}
    </span>
  )
}
