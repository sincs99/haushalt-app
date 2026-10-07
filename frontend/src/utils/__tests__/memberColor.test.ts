import { describe, it, expect } from 'vitest'
import { getMemberColor } from '../memberColor'

describe('getMemberColor', () => {
  it('is deterministic for the same user id', () => {
    expect(getMemberColor('user-abc')).toBe(getMemberColor('user-abc'))
  })

  it('maps by char-code sum modulo palette size', () => {
    // 'a' = 97 → 97 % 4 = 1 → second colour
    expect(getMemberColor('a')).toBe('var(--p2)')
    // 'b' = 98 → 2
    expect(getMemberColor('b')).toBe('var(--member-3)')
    // 'd' = 100 → 0
    expect(getMemberColor('d')).toBe('var(--p1)')
    // 'c' = 99 → 3
    expect(getMemberColor('c')).toBe('var(--member-4)')
  })

  it('always returns a palette colour, including for the empty string', () => {
    const palette = ['var(--p1)', 'var(--p2)', 'var(--member-3)', 'var(--member-4)']
    for (const id of ['', 'x', '123e4567-e89b-12d3-a456-426614174000']) {
      expect(palette).toContain(getMemberColor(id))
    }
  })
})
