/** Only a literal, origin-relative application path is a valid post-login target. */
export function internalRedirect(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return
  if (/[\\\u0000-\u0020\u007f]/.test(value)) return
  // Reject encoded separators/control characters too; downstream decoding must not
  // turn a seemingly relative path into a network-path reference.
  if (/%(?:2f|5c|0[0-9a-f]|1[0-9a-f]|20|7f|25)/i.test(value)) return
  const path = value.split(/[?#]/, 1)[0]
  if (path === '/login' || path === '/register') return
  return value
}
