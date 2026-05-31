export interface Need {
  id: number
  code: string
  label: string
  shortLabel: string
  emoji: string
}

export const NEEDS: Need[] = [
  { id: 1,  code: 'being_chosen',          label: 'Being perfectly chosen',      shortLabel: 'Being chosen',      emoji: '💝' },
  { id: 2,  code: 'surviving',             label: 'Surviving the unsurvivable',  shortLabel: 'Survival',          emoji: '🔥' },
  { id: 3,  code: 'procedural_resolution', label: 'Procedural resolution',       shortLabel: 'Solving mysteries', emoji: '🔍' },
  { id: 4,  code: 'moral_complexity',      label: 'Moral complexity',            shortLabel: 'Moral depth',       emoji: '⚖️' },
  { id: 5,  code: 'power_agency',          label: 'Power & agency',              shortLabel: 'Power',             emoji: '⚡' },
  { id: 6,  code: 'wound_visible',         label: 'The wound made visible',      shortLabel: 'Trauma witnessed',  emoji: '🩹' },
  { id: 7,  code: 'making_sense_history',  label: 'Making sense of history',     shortLabel: 'History',           emoji: '📜' },
  { id: 8,  code: 'self_remade',           label: 'The self can be remade',      shortLabel: 'Reinvention',       emoji: '🦋' },
  { id: 9,  code: 'inside_power',          label: 'Being inside power',          shortLabel: 'Elite worlds',      emoji: '🏛️' },
  { id: 10, code: 'identity_witnessed',    label: 'Identity witnessed',          shortLabel: 'Being seen',        emoji: '👁️' },
  { id: 11, code: 'world_larger',          label: 'The world is larger',         shortLabel: 'Wonder',            emoji: '🌍' },
  { id: 12, code: 'creative_kinship',      label: 'Creative kinship',            shortLabel: 'Artists & makers',  emoji: '🎨' },
  { id: 13, code: 'anxiety_named',         label: 'Anxiety named & held',        shortLabel: 'Anxiety',           emoji: '🌊' },
]

export const NEED_BY_ID: Record<number, Need> = Object.fromEntries(NEEDS.map(n => [n.id, n]))
