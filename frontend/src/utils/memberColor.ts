/**
 * Deterministisches Mapping User-ID → CSS-Farb-Variable.
 * Derselbe User hat überall dieselbe Farbe.
 */
const MEMBER_COLORS = [
  'var(--p1)',       // Teal
  'var(--p2)',       // Rosa
  'var(--member-3)', // Mauve
  'var(--member-4)', // Olive
] as const

export function getMemberColor(userId: string): string {
  let hash = 0
  for (const ch of userId) {
    hash += ch.charCodeAt(0)
  }
  return MEMBER_COLORS[hash % MEMBER_COLORS.length]
}
