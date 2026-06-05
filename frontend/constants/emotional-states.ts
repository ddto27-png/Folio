// Shared constants for the 1–5 emotional state scale and signal types.
// Both LogReadModal and InlineBookLogger use these — keeping them here
// means a label change only needs to happen once.

// The 1–5 emotional state scale used throughout the scoring engine.
// label     — longer form for dropdowns and select elements
// chipLabel — shorter form for pill/chip button UIs
export const EMOTIONAL_STATES = [
  { value: 1, label: '1 — In crisis',   chipLabel: 'In a dark place' },
  { value: 2, label: '2 — Struggling',  chipLabel: 'A bit low' },
  { value: 3, label: '3 — Neutral',     chipLabel: 'Just okay' },
  { value: 4, label: '4 — Doing well',  chipLabel: 'Pretty good' },
  { value: 5, label: '5 — Thriving',    chipLabel: 'Really happy' },
]

// Signal types — map to SIGNAL_WEIGHTS in scoring.py.
// Scores range from +1.0 (star_5) to -0.8 (star_1), with re_read as a strong positive.
export const SIGNALS = [
  { value: 'star_5',    label: '★★★★★  Loved it' },
  { value: 'star_4',    label: '★★★★  Really liked it' },
  { value: 'star_3',    label: '★★★  It was okay' },
  { value: 'star_2',    label: '★★  Didn\'t like it' },
  { value: 'star_1',    label: '★  Disliked it' },
  { value: 'abandoned', label: '✕  Abandoned' },
  { value: 're_read',   label: '↩  Re-read' },
]
