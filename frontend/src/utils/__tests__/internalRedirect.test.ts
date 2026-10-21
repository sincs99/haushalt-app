import { expect, test } from 'vitest'
import { internalRedirect } from '../internalRedirect'

test.each(['//evil.test', '/\\evil.test', '/%2fevil.test', '/%5cevil.test', '/%252fevil.test',
  '/\nevil.test', '/login', '/register?redirect=/dashboard', 'https://evil.test', ['//evil.test'], null])(
  'rejects unsafe or recursive redirect %s', (value) => { expect(internalRedirect(value)).toBeUndefined() },
)

test.each(['/dashboard', '/t/opaque-token', '/notes?tag=WG#pinned'])('preserves local target %s', (value) => {
  expect(internalRedirect(value)).toBe(value)
})
