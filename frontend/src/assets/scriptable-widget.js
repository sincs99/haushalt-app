// Haushalt App – Homescreen-Widget für Scriptable (iOS)
// Variables used by Scriptable.
// icon-color: brown; icon-glyph: home;
//
// Einrichtung: Scriptable aus dem App Store laden, neues Skript anlegen,
// diesen Text einfügen, Widget „Scriptable“ auf den Homescreen legen und
// dieses Skript auswählen. Grössen: klein, mittel, gross.
//
// Der Schlüssel unten darf nur lesen (Aufgaben, Ämtli, Pflege, Einkauf,
// Termine von heute). In der App unter Haushalt → Widget lässt er sich
// jederzeit widerrufen.

const BASE_URL = '__BASE_URL__'
const WIDGET_KEY = '__WIDGET_KEY__'
const LANG = '__LANG__'

const TEXT = {
  de: {
    today: 'Heute',
    nothing: 'Nichts fällig 🎉',
    shopping: 'Einkauf',
    open: 'offen',
    events: 'Termine',
    allDay: 'ganztägig',
    more: 'weitere',
    offline: 'Offline – Stand',
    invalid: 'Widget-Schlüssel ungültig. In der App unter Haushalt → Widget neu erzeugen.',
    error: 'Daten konnten nicht geladen werden.',
  },
  en: {
    today: 'Today',
    nothing: 'Nothing due 🎉',
    shopping: 'Shopping',
    open: 'open',
    events: 'Events',
    allDay: 'all day',
    more: 'more',
    offline: 'Offline – as of',
    invalid: 'Widget key invalid. Create a new one in the app under Household → Widget.',
    error: 'Could not load data.',
  },
}[LANG] || {}

// Farben wie in der App (Light / Dark)
const C = {
  bg: Color.dynamic(new Color('#FBF8F3'), new Color('#22302D')),
  ink: Color.dynamic(new Color('#3A423F'), new Color('#E8EFEC')),
  sub: Color.dynamic(new Color('#5D6A66'), new Color('#96A4A0')),
  acc: Color.dynamic(new Color('#896140'), new Color('#C79A6E')),
  danger: Color.dynamic(new Color('#DC2626'), new Color('#E86E6E')),
}

const KIND_SYMBOL = { todo: 'checklist', chore: 'sparkles', pet: 'pawprint', plant: 'leaf' }
const CACHE = FileManager.local().joinPath(FileManager.local().documentsDirectory(), 'haushalt-widget.json')

async function load() {
  const req = new Request(`${BASE_URL}/api/widget/summary?lang=${LANG}`)
  req.headers = { Authorization: `Bearer ${WIDGET_KEY}` }
  req.timeoutInterval = 15
  try {
    const data = await req.loadJSON()
    const status = req.response && req.response.statusCode
    if (status === 401) return { error: TEXT.invalid }
    if (status !== 200) throw new Error(`HTTP ${status}`)
    FileManager.local().writeString(CACHE, JSON.stringify(data))
    return { data }
  } catch (e) {
    if (FileManager.local().fileExists(CACHE)) {
      return { data: JSON.parse(FileManager.local().readString(CACHE)), offline: true }
    }
    return { error: TEXT.error }
  }
}

function addText(stack, text, font, color, lines = 1) {
  const t = stack.addText(text)
  t.font = font
  t.textColor = color
  t.lineLimit = lines
  return t
}

function addSymbolRow(stack, symbol, text, color, size) {
  const row = stack.addStack()
  row.centerAlignContent()
  row.spacing = 6
  const img = row.addImage(SFSymbol.named(symbol).image)
  img.imageSize = new Size(size, size)
  img.tintColor = color
  addText(row, text, Font.systemFont(size), color)
  return row
}

function header(w, data, family) {
  const top = w.addStack()
  top.centerAlignContent()
  addText(top, family === 'small' ? TEXT.today : `${TEXT.today} · ${data.household}`, Font.semiboldRoundedSystemFont(14), C.ink)
  top.addSpacer()
  addText(top, String(data.due_count), Font.boldRoundedSystemFont(family === 'small' ? 28 : 20), data.due_count ? C.acc : C.sub)
}

function dueList(w, data, max, size) {
  if (!data.due.length) {
    addText(w, TEXT.nothing, Font.systemFont(size), C.sub)
    return
  }
  for (const item of data.due.slice(0, max)) {
    addSymbolRow(w, KIND_SYMBOL[item.kind] || 'circle', item.title, item.overdue ? C.danger : C.ink, size)
    w.addSpacer(3)
  }
  const rest = data.due_count - Math.min(max, data.due.length)
  if (rest > 0) addText(w, `+${rest} ${TEXT.more}`, Font.systemFont(size - 2), C.sub)
}

function shopping(w, data, max, size) {
  const s = data.shopping
  addSymbolRow(w, 'cart', `${TEXT.shopping}: ${s.open_count} ${TEXT.open}`, C.sub, size)
  if (max > 0 && s.items.length) {
    w.addSpacer(2)
    addText(w, s.items.slice(0, max).join(' · '), Font.systemFont(size - 1), C.sub, 2)
  }
}

function events(w, data, size) {
  if (!data.events.length) return
  w.addSpacer(6)
  addText(w, TEXT.events, Font.semiboldRoundedSystemFont(size), C.ink)
  for (const e of data.events) {
    addSymbolRow(w, 'calendar', `${e.time || TEXT.allDay} ${e.title}`, C.sub, size - 1)
  }
}

async function build() {
  const family = config.widgetFamily || 'large'
  const w = new ListWidget()
  w.backgroundColor = C.bg
  w.setPadding(14, 14, 14, 14)
  w.url = `${BASE_URL}/dashboard`
  // iOS entscheidet selbst; das ist nur der frühestmögliche Zeitpunkt
  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000)

  const { data, error, offline } = await load()
  if (error) {
    addText(w, error, Font.systemFont(12), C.sub, 4)
    return w
  }

  header(w, data, family)
  w.addSpacer(8)
  if (family === 'small') {
    dueList(w, data, 3, 12)
  } else if (family === 'medium') {
    dueList(w, data, 3, 13)
    w.addSpacer()
    shopping(w, data, 0, 12)
  } else {
    dueList(w, data, 8, 14)
    events(w, data, 13)
    w.addSpacer()
    shopping(w, data, 6, 13)
  }
  w.addSpacer()
  if (offline) {
    const time = new Date(data.generated_at).toLocaleTimeString(LANG, { hour: '2-digit', minute: '2-digit' })
    addText(w, `${TEXT.offline} ${time}`, Font.systemFont(10), C.sub)
  }
  return w
}

const widget = await build()
if (config.runsInWidget) {
  Script.setWidget(widget)
} else {
  await widget.presentLarge()
}
Script.complete()
