import { expect, test } from 'vitest'
import { buildWidgetScript } from '../widgetScript'

function setting(script: string, name: string): string {
  return JSON.parse(script.match(new RegExp(`^const ${name} = (.+)$`, 'm'))![1]!)
}

test('embeds escaped values and a stable non-secret cache namespace', async () => {
  const script = await buildWidgetScript('https://casa.example.com/', 'hw_abc-123_XYZ', 'en')
  expect(setting(script, 'BASE_URL')).toBe('https://casa.example.com')
  expect(setting(script, 'WIDGET_KEY')).toBe('hw_abc-123_XYZ')
  expect(setting(script, 'LANG')).toBe('en')
  expect(setting(script, 'CACHE_ID')).toMatch(/^[a-f0-9]{64}$/)
  expect(script).not.toContain('__')
  expect(setting(await buildWidgetScript('https://casa.example.com', 'hw_abc-123_XYZ', 'en'), 'CACHE_ID'))
    .toBe(setting(script, 'CACHE_ID'))
})

test('isolates caches by server, token and language', async () => {
  const scripts = await Promise.all([
    buildWidgetScript('https://a', 'hw_one', 'de'),
    buildWidgetScript('https://b', 'hw_one', 'de'),
    buildWidgetScript('https://a', 'hw_two', 'de'),
    buildWidgetScript('https://a', 'hw_one', 'en'),
  ])
  expect(new Set(scripts.map(s => setting(s, 'CACHE_ID'))).size).toBe(4)
  expect(setting(await buildWidgetScript('https://a', 'hw_one', 'fr'), 'CACHE_ID'))
    .toBe(setting(scripts[0]!, 'CACHE_ID'))
})

test('quotes newlines, quotes and replacement metacharacters as data', async () => {
  const value = "https://x'\n;throw new Error('injected'); //\\$&"
  const script = await buildWidgetScript(value, value, 'de')
  expect(setting(script, 'BASE_URL')).toBe(value)
  expect(setting(script, 'WIDGET_KEY')).toBe(value)
})

// Run the actual loader against a bounded Scriptable fixture; no real I/O.
async function load(script: string, disk: Map<string, string>, status?: number, throws = false) {
  class Request {
    response = status === undefined ? undefined : { statusCode: status }
    headers = {}
    timeoutInterval = 0
    async loadJSON() {
      if (throws) throw new Error('fixture request failure')
      return { household: 'Dummy', generated_at: new Date().toISOString(), due: [] }
    }
  }
  const files = {
    joinPath: (a: string, b: string) => `${a}/${b}`,
    documentsDirectory: () => '/fixture',
    fileExists: (p: string) => disk.has(p),
    writeString: (p: string, data: string) => disk.set(p, data),
    readString: (p: string) => disk.get(p),
    remove: (p: string) => disk.delete(p),
  }
  class Color { static dynamic() { return null } }
  const run = new Function('FileManager', 'Request', 'Color',
    script.slice(0, script.indexOf('function addText')) + '\nreturn load()')
  return run({ local: () => files }, Request, Color)
}

test('offline cache belongs to exactly one generated script', async () => {
  const disk = new Map<string, string>()
  const a = await buildWidgetScript('https://a', 'hw_one', 'de')
  const b = await buildWidgetScript('https://a', 'hw_two', 'de')
  expect((await load(a, disk, 200)).data.household).toBe('Dummy')
  expect((await load(a, disk, undefined, true)).offline).toBe(true)
  expect((await load(b, disk, undefined, true)).error).toBeTruthy()
})

test.each([false, true])('known 401 clears cache even when loadJSON throws=%s', async throws => {
  const disk = new Map<string, string>()
  const script = await buildWidgetScript('https://a', 'hw_one', 'de')
  await load(script, disk, 200)
  expect((await load(script, disk, 401, throws)).error).toContain('ungültig')
  expect(disk.size).toBe(0)
  expect((await load(script, disk, undefined, true)).data).toBeUndefined()
})

test.each(['invalid-json', 'wrong-origin', 'expired'])('rejects %s cache', async variant => {
  const disk = new Map<string, string>()
  const script = await buildWidgetScript('https://a', 'hw_one', 'de')
  await load(script, disk, 200)
  const filename = [...disk.keys()][0]!
  const cached = JSON.parse(disk.get(filename)!)
  if (variant === 'wrong-origin') cached.origin = 'https://other'
  if (variant === 'expired') cached.saved_at = Date.now() - 25 * 60 * 60 * 1000
  disk.set(filename, variant === 'invalid-json' ? '{broken' : JSON.stringify(cached))
  expect((await load(script, disk, undefined, true)).data).toBeUndefined()
  expect(disk.size).toBe(0)
})
