/* eslint-disable */
/**
 * Mobile-Layout-Audit (QA-Werkzeug, nicht Teil des Builds).
 *
 * Öffnet jede Route in mehreren Viewports/Themes/Sprachen, klickt Tabs und
 * „Hinzufügen/Bearbeiten“-Dialoge auf, macht Screenshots und prüft das Layout
 * automatisch (horizontaler Scroll, Text-Überlauf, überlappende Geschwister,
 * Tap-Ziele < 44 px, Inhalt unter Bottom-Nav/Safe-Area, abgeschnittener Inhalt).
 *
 * Voraussetzungen: Backend + `npm run dev` laufen, Testdaten angelegt
 * (qa/seed-testdata.py), Playwright global installiert.
 *
 *   NODE_PATH=$(npm root -g) node qa/mobile-audit.cjs [--quick] [--only=/route] [--out=qa/mobile/run1]
 *
 * Ergebnis: Screenshots + findings.json im Ausgabeordner (qa/mobile/ ist in .gitignore).
 */
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')

const args = Object.fromEntries(process.argv.slice(2).map(a => {
  const [k, v] = a.replace(/^--/, '').split('=')
  return [k, v ?? true]
}))
const BASE = process.env.QA_BASE || 'http://localhost:5173'
const OUT = path.resolve(args.out || 'qa/mobile/run')
const SEED = JSON.parse(fs.readFileSync(process.env.QA_SEED || 'qa/mobile/seed.json', 'utf8'))
const USER = { email: 'anna@example.ch', password: 'Testpasswort123!' }
const NOHH = { email: 'nohh@example.ch', password: 'Testpasswort123!' }

// Android ohne Insets, iPhones mit Home-Indicator unten. Oben kein Inset: mit
// apple-mobile-web-app-status-bar-style=default liegt der Inhalt unter der Statusleiste.
const VIEWPORTS = [
  { name: '360x780', width: 360, height: 780, insets: { top: 0, bottom: 0 } },
  { name: '390x844', width: 390, height: 844, insets: { top: 0, bottom: 34 } },
  { name: '430x932', width: 430, height: 932, insets: { top: 0, bottom: 34 } },
]
const KEYBOARD = { name: '390x500kb', width: 390, height: 500, insets: { top: 0, bottom: 0 } }

const ROUTES = [
  { path: '/dashboard' },
  { path: '/shopping' },
  { path: '/todos' },
  { path: '/chores' },
  { path: '/expenses' },
  { path: '/calendar' },
  { path: '/pets' },
  { path: `/pets/${SEED.pet}`, name: 'pet-detail' },
  { path: '/plants' },
  { path: `/plants/${SEED.plant}`, name: 'plant-detail' },
  { path: '/food' },
  { path: '/notes' },
  { path: '/documents' },
  { path: '/household' },
  { path: '/tags' },
  { path: `/t/${SEED.tag.token}`, name: 'tag-scan' },
  { path: '/assistant' },
  { path: '/login', anon: true },
  { path: '/register', anon: true },
  { path: '/no-household', user: NOHH },
]

// Zusätzliche Zustände pro Route: [Name, Klick-Selektoren nacheinander, overlay?]
const EXTRA = {
  '/shopping': [['item-edit', ['.item-row__name'], true], ['store-menu', ['.group-header__kebab'], false]],
  '/todos': [['details-form', ['summary, .details-toggle, button:has-text("Details")'], false], ['edit-inline', ['.todo-row__actions button'], false]],
  '/chores': [['chore-edit', ['.chore-card__actions button'], false]],
  '/expenses': [['expense-edit', ['.expense-row__main, .expense-item__main'], true]],
  '/calendar': [['day-week', ['.week-strip__day >> nth=3'], false], ['day-month', ['.pill-tab >> nth=1', '.month-grid__cell >> nth=10'], false], ['event-edit', ['.event-card'], true]],
  'pet-detail': [['care-task-add', ['.icon-btn'], true], ['med-add', ['button:has-text("Medikament hinzufügen"), button:has-text("Add medication")'], true]],
  'plant-detail': [['task-add', ['button:has-text("Pflegeaufgabe"), button:has-text("care task")'], true]],
  '/food': [['meal-detail', ['.week-row >> nth=2'], true], ['meal-poll', ['button:has-text("Abstimmung starten"), button:has-text("Start poll")'], true]],
  '/notes': [['note-edit', ['.note-card'], true]],
  '/documents': [['doc-edit', ['.doc-card'], true], ['upload', ['button:has-text("Hochladen"), button:has-text("Upload")'], true]],
  '/household': [['leave-confirm', ['button:has-text("Haushalt verlassen"), button:has-text("Leave household")'], true]],
  '/tags': [['tag-detail', ['.tag-row'], true]],
}

const OPEN_RE = /(hinzufügen|bezahlt markieren|mark as paid|neue[rs]?\b|neu\b|erstellen|anlegen|bearbeiten|verwalten|ausgleich|begleichen|einstellungen|^add|\badd\b|new\b|create|edit|manage|settle|^\+$)/i
const DANGER_RE = /(lösch|delete|entfern|remove|abmeld|logout|log out|verlass|leave|rotate|erneuern|regenerate)/i

// ---------------------------------------------------------------- Audit (im Browser)
function auditInPage(opts) {
  // Konfigurierte Viewport-Breite: mit isMobile weitet Chromium den Layout-Viewport
  // auf die Inhaltsbreite aus, innerWidth würde horizontalen Überlauf verschleiern.
  const vw = opts.vw || window.innerWidth
  const vh = opts.vh || window.innerHeight
  const findings = []
  const sig = el => {
    if (!el || el === document.body) return 'body'
    const cls = [...el.classList].filter(c => !c.startsWith('data-v')).slice(0, 2).join('.')
    const parent = el.parentElement
    const pcls = parent ? [...parent.classList].slice(0, 1).join('.') : ''
    return `${pcls ? '.' + pcls + ' > ' : ''}${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`
  }
  const txt = el => (el.innerText || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 50)
  const add = (type, el, detail) => findings.push({ type, sig: sig(el), text: txt(el), detail })
  const isVisible = el => {
    const cs = getComputedStyle(el)
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0
  }
  const clipsX = el => /(auto|scroll|hidden|clip)/.test(getComputedStyle(el).overflowX)
  const clippedByAncestor = el => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (clipsX(p)) return true
      if (getComputedStyle(p).position === 'fixed') return false
    }
    return false
  }
  const els = [...document.body.querySelectorAll('*')].filter(el =>
    !(el instanceof SVGElement && el.tagName.toLowerCase() !== 'svg') &&
    !['SCRIPT', 'STYLE', 'TEMPLATE', 'BR', 'OPTION'].includes(el.tagName) && isVisible(el))

  // Root für die Prüfung: offener Dialog/Sheet, sonst die ganze Seite
  const overlay = [...document.querySelectorAll('[role=dialog], .sheet-overlay, .dialog-overlay, .dialog-backdrop, .sheet, .more-sheet')]
    .filter(isVisible).pop()
  const scope = opts.scopeOverlay && overlay ? overlay : document.body
  const inScope = el => scope.contains(el)

  // 1. horizontaler Scroll / Elemente ausserhalb
  const sw = document.documentElement.scrollWidth
  if (sw > vw + 1) findings.push({ type: 'h-scroll', sig: 'document', text: '', detail: `scrollWidth ${sw} > ${vw}` })
  for (const el of els) {
    if (!inScope(el)) continue
    const r = el.getBoundingClientRect()
    if ((r.right > vw + 1 || r.left < -1) && !clippedByAncestor(el)) {
      const p = el.parentElement
      if (p) {
        const pr = p.getBoundingClientRect()
        if ((pr.right > vw + 1 || pr.left < -1) && !clippedByAncestor(p)) continue // nur oberster Verursacher
      }
      add('out-of-viewport', el, `left ${Math.round(r.left)} right ${Math.round(r.right)} vw ${vw}`)
    }
  }

  // 2. Text überragt Element (ohne overflow-Handling)
  for (const el of els) {
    if (!inScope(el)) continue
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
    if (!hasText) continue
    const cs = getComputedStyle(el)
    if (cs.display.startsWith('inline') && cs.display !== 'inline-block' && cs.display !== 'inline-flex') continue
    if (cs.overflowX !== 'visible') continue
    // .tap-target: das unsichtbare ::after zählt in scrollWidth mit
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0 && !el.classList.contains('tap-target')) {
      add('text-overflow', el, `scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}`)
    }
  }

  // 3. überlappende Geschwister in Flex/Grid
  for (const el of els) {
    if (!inScope(el)) continue
    const d = getComputedStyle(el).display
    if (!/(flex|grid)/.test(d)) continue
    const kids = [...el.children].filter(k => isVisible(k) && !/(absolute|fixed|sticky)/.test(getComputedStyle(k).position))
    for (let i = 0; i < kids.length; i++) {
      const a = kids[i].getBoundingClientRect()
      for (let j = i + 1; j < kids.length; j++) {
        const b = kids[j].getBoundingClientRect()
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left)
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
        if (ox > 1 && oy > 1) {
          add('sibling-overlap', kids[i], `überlappt ${sig(kids[j])} „${txt(kids[j])}“ um ${Math.round(ox)}×${Math.round(oy)}`)
        }
      }
    }
  }

  // 4. Tap-Ziele < 44×44
  const interactive = els.filter(el => inScope(el) && el.matches(
    'a[href], button, select, textarea, input:not([type=hidden]), [role=button], [role=tab], [role=checkbox], [role=switch]'))
  const isFixedish = el => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const pos = getComputedStyle(p).position
      if (pos === 'fixed' || pos === 'sticky') return p
    }
    return null
  }
  const hitboxes = []
  for (const el of interactive) {
    const cs = getComputedStyle(el)
    if (el.tagName === 'A' && cs.display === 'inline') continue // Fliesstext-Link
    if (el.closest('.bottom-nav') && opts.scopeOverlay) continue
    const r = el.getBoundingClientRect()
    // Checkbox/Radio im <label>: das Label ist das Tap-Ziel
    let w = r.width, h = r.height
    const lab = el.closest('label')
    if (lab && el.matches('input')) { const lr = lab.getBoundingClientRect(); w = Math.max(w, lr.width); h = Math.max(h, lr.height) }
    // Hitbox-Vergrösserung per ::before/::after (position:absolute, negatives inset)
    for (const pseudo of ['::before', '::after']) {
      const ps = getComputedStyle(el, pseudo)
      if (ps.content === 'none' || ps.position !== 'absolute') continue
      const px = v => (v.endsWith('px') ? parseFloat(v) : 0)
      w = Math.max(w, r.width - px(ps.left) - px(ps.right))
      h = Math.max(h, r.height - px(ps.top) - px(ps.bottom))
    }
    // vergrösserte Hitbox wird von overflow-Vorfahren (Scroll-Container, Karten) abgeschnitten
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const pcs = getComputedStyle(p)
      if (pcs.overflowX !== 'visible' || pcs.overflowY !== 'visible') {
        const pr = p.getBoundingClientRect()
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2
        // (teilweise) weggescrollt: nicht vollständig sichtbar, wird beim Scrollen geprüft
        if (/(auto|scroll)/.test(pcs.overflowX + pcs.overflowY) && (r.left < pr.left - 1 || r.right > pr.right + 1 || r.top < pr.top - 1 || r.bottom > pr.bottom + 1)) { w = h = Infinity; break }
        w = Math.min(w, 2 * Math.min(cx - pr.left, pr.right - cx))
        h = Math.min(h, 2 * Math.min(cy - pr.top, pr.bottom - cy))
        w = Math.max(w, r.width); h = Math.max(h, r.height)
      }
      if (pcs.position === 'fixed') break
    }
    if (w < 43.5 || h < 43.5) add('tap-target', el, `${Math.round(w)}×${Math.round(h)}`)
    if (isFinite(w) && isFinite(h)) hitboxes.push({ el, r, hb: { left: r.left + r.width / 2 - w / 2, right: r.left + r.width / 2 + w / 2, top: r.top + r.height / 2 - h / 2, bottom: r.top + r.height / 2 + h / 2 }, grown: w > r.width + 1 || h > r.height + 1 })
  }
  // vergrösserte Tap-Fläche liegt über einem sichtbaren Nachbar-Bedienelement
  for (const a of hitboxes) {
    if (!a.grown) continue
    for (const b of hitboxes) {
      if (a === b || a.el.contains(b.el) || b.el.contains(a.el)) continue
      // fixe/sticky Elemente (Bottom-Nav, FAB, Sticky-Pill) liegen oben und bekommen den Tap selbst
      if (isFixedish(b.el) && !isFixedish(a.el)) continue
      const ox = Math.min(a.hb.right, b.r.right) - Math.max(a.hb.left, b.r.left)
      const oy = Math.min(a.hb.bottom, b.r.bottom) - Math.max(a.hb.top, b.r.top)
      if (ox > 1 && oy > 1) add('hitbox-overlap', a.el, `Tap-Fläche überdeckt ${sig(b.el)} „${txt(b.el)}“ (${Math.round(ox)}×${Math.round(oy)})`)
    }
  }

  // 5. unter Bottom-Nav / Safe-Area
  const nav = document.querySelector('.bottom-nav')
  const navTop = nav && isVisible(nav) ? nav.getBoundingClientRect().top : vh
  const safeBottom = vh - (opts.insets?.bottom || 0)
  const safeTop = opts.insets?.top || 0

  if (opts.checkNav) {
    // Seite ist ans Ende gescrollt: letzter Inhalt darf nicht hinter der Nav liegen
    for (const el of interactive.concat(els.filter(e => e.matches('p, h1, h2, h3, li, .card, [class*="card"]')))) {
      if (isFixedish(el) || (nav && nav.contains(el))) continue
      const r = el.getBoundingClientRect()
      if (r.bottom > navTop + 1 && r.top < navTop) add('under-bottom-nav', el, `bottom ${Math.round(r.bottom)} > navTop ${Math.round(navTop)}`)
    }
    // Fixe Elemente (FAB etc.) verdecken am Seitenende Tap-Ziele im Inhalt
    const fixedEls = els.filter(e => getComputedStyle(e).position === 'fixed' && !(nav && (nav === e || nav.contains(e))) && e.getBoundingClientRect().height < vh / 2)
    for (const f of fixedEls) {
      const fr = f.getBoundingClientRect()
      for (const el of interactive) {
        if (f.contains(el) || isFixedish(el)) continue
        const r = el.getBoundingClientRect()
        const ox = Math.min(r.right, fr.right) - Math.max(r.left, fr.left)
        const oy = Math.min(r.bottom, fr.bottom) - Math.max(r.top, fr.top)
        if (ox > 2 && oy > 2) add('covered-by-fixed', el, `von ${sig(f)} „${txt(f)}“ verdeckt (${Math.round(ox)}×${Math.round(oy)})`)
      }
    }
  }
  // Sichtbarer Bereich innerhalb scrollender Vorfahren (Dialog-Body etc.)
  const hiddenInScroller = el => {
    const r = el.getBoundingClientRect()
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (/(auto|scroll)/.test(getComputedStyle(p).overflowY)) {
        const pr = p.getBoundingClientRect()
        if (r.top >= pr.bottom - 1 || r.bottom <= pr.top + 1) return true
        if (r.bottom > pr.bottom + 1) return 'partial'
      }
    }
    return false
  }
  for (const el of interactive) {
    const fx = isFixedish(el)
    if (hiddenInScroller(el)) continue
    if (!fx || (nav && nav.contains(el))) continue
    const r = el.getBoundingClientRect()
    if (r.bottom > safeBottom + 1 && r.top < vh) add('in-safe-area-bottom', el, `bottom ${Math.round(r.bottom)} > ${safeBottom}`)
    if (r.top < safeTop - 1 && r.bottom > 0) add('in-safe-area-top', el, `top ${Math.round(r.top)} < ${safeTop}`)
    if (nav && isVisible(nav) && !nav.contains(el) && fx !== nav && !overlay) {
      if (r.bottom > navTop + 1 && r.top < vh) add('fixed-over-bottom-nav', el, `bottom ${Math.round(r.bottom)} > navTop ${Math.round(navTop)}`)
    }
  }

  // 6. abgeschnittener Inhalt (feste Höhe + overflow hidden) / Dialog höher als Viewport
  for (const el of els) {
    if (!inScope(el)) continue
    const cs = getComputedStyle(el)
    const oy = cs.overflowY
    if (cs.textOverflow === 'ellipsis' || cs.webkitLineClamp !== 'none' && cs.webkitLineClamp) continue
    if ((oy === 'hidden' || oy === 'clip') && el.scrollHeight > el.clientHeight + 2 && el.clientHeight > 0) {
      if (el.matches('img, video, canvas')) continue
      add('clipped', el, `scrollHeight ${el.scrollHeight} > clientHeight ${el.clientHeight}`)
    }
    if (oy === 'visible' && el.scrollHeight > el.clientHeight + 2 && el.clientHeight > 0 && !/(inline)/.test(cs.display) && cs.height !== 'auto') {
      // Kinder ragen unten heraus (feste Höhe)
      const r = el.getBoundingClientRect()
      const spill = [...el.children].some(k => isVisible(k) && getComputedStyle(k).position !== 'absolute' && k.getBoundingClientRect().bottom > r.bottom + 2)
      if (spill) add('v-spill', el, `scrollHeight ${el.scrollHeight} > clientHeight ${el.clientHeight}`)
    }
  }
  for (const d of document.querySelectorAll('[role=dialog], .more-sheet, .sheet, .dialog-panel, .dialog-content')) {
    if (!isVisible(d)) continue
    const r = d.getBoundingClientRect()
    const cs = getComputedStyle(d)
    const scrolls = /(auto|scroll)/.test(cs.overflowY) || [...d.querySelectorAll('*')].some(c => /(auto|scroll)/.test(getComputedStyle(c).overflowY) && c.scrollHeight > c.clientHeight)
    if ((r.bottom > vh + 1 || r.top < -1) && !scrolls) add('dialog-exceeds-viewport', d, `top ${Math.round(r.top)} bottom ${Math.round(r.bottom)} vh ${vh}`)
  }

  // Dedupe nach Typ+Signatur
  const seen = new Map()
  for (const f of findings) {
    const k = f.type + '|' + f.sig
    if (!seen.has(k)) seen.set(k, { ...f, count: 1 })
    else seen.get(k).count++
  }
  return [...seen.values()]
}

// ---------------------------------------------------------------- Ablauf
async function login(page, user) {
  await page.goto(BASE + '/login')
  await page.locator('input[type=email]').fill(user.email)
  await page.locator('input[type=password]').fill(user.password)
  await page.locator('button[type=submit]').click()
  await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 10000 })
}

async function settle(page) {
  await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {})
  await page.waitForTimeout(900)
}

async function setInsets(page, insets) {
  const c = await page.context().newCDPSession(page)
  await c.send('Emulation.setSafeAreaInsetsOverride', { insets })
}

async function scrollToBottom(page) {
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await page.waitForTimeout(150)
}

function slug(s) {
  return s.replace(/^\//, '').replace(/[^a-z0-9]+/gi, '-').replace(/-+$/, '').slice(0, 40) || 'root'
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const browser = await chromium.launch()
  const all = []
  const quick = !!args.quick
  const routes = ROUTES.filter(r => !args.only || r.path.startsWith(args.only) || r.name === args.only)
  const combos = []
  for (const vp of VIEWPORTS) {
    for (const theme of ['light', 'dark']) combos.push({ vp, theme, locale: 'de', shots: true })
    combos.push({ vp, theme: 'light', locale: 'en', shots: vp.width === 360 })
  }
  const run = quick ? combos.filter(c => c.theme === 'light') : combos

  for (const c of run) {
    for (const user of [USER, NOHH, null]) {
      const context = await browser.newContext({
        viewport: { width: c.vp.width, height: c.vp.height }, deviceScaleFactor: 1,
        isMobile: true, hasTouch: true, colorScheme: c.theme,
      })
      await context.addInitScript(([theme, locale]) => {
        localStorage.setItem('casa_theme', theme)
        localStorage.setItem('haushalt_locale', locale)
      }, [c.theme, c.locale])
      const page = await context.newPage()
      if (user) await login(page, user)
      await setInsets(page, c.vp.insets)
      const mine = routes.filter(r => (user === USER && !r.anon && !r.user) || (user === NOHH && r.user === NOHH) || (!user && r.anon))
      for (const route of mine) {
        const base = `${route.name || slug(route.path)}__${c.vp.name}_${c.theme}_${c.locale}`
        const record = async (state, opts = {}) => {
          const res = await page.evaluate(auditInPage, { insets: c.vp.insets, vw: c.vp.width, vh: c.vp.height, scopeOverlay: !!opts.overlay, checkNav: !!opts.checkNav })
          for (const f of res) all.push({ route: route.name || route.path, state, viewport: c.vp.name, theme: c.theme, locale: c.locale, ...f })
          if (c.shots) {
            await page.screenshot({ path: path.join(OUT, `${base}${state === 'base' ? '' : '--' + slug(state)}.png`), fullPage: !opts.overlay && !opts.viewportOnly })
          }
        }
        await page.goto(BASE + route.path)
        await settle(page)
        await record('base')
        await scrollToBottom(page)
        await record('scrolled-bottom', { viewportOnly: true, checkNav: true })
        await page.evaluate(() => window.scrollTo(0, 0))

        // Tabs durchklicken
        const tabs = await page.locator('.pill-tab:not(.pill-tab--add), [role=tab]').all()
        const tabLabels = []
        for (const t of tabs) { if (await t.isVisible()) tabLabels.push((await t.innerText()).trim()) }
        for (let i = 1; i < tabLabels.length && i < 8; i++) {
          const t = page.locator('.pill-tab:not(.pill-tab--add), [role=tab]').filter({ hasText: tabLabels[i] }).first()
          if (!(await t.isVisible().catch(() => false))) continue
          await t.click().catch(() => {})
          await settle(page)
          await record('tab-' + tabLabels[i])
        }
        if (tabLabels.length > 1) {
          await page.locator('.pill-tab:not(.pill-tab--add), [role=tab]').filter({ hasText: tabLabels[0] }).first().click().catch(() => {})
          await settle(page)
        }

        // Dialoge öffnen (nur ungefährliche Buttons)
        if (c.theme === 'light' && (c.locale === 'de' || c.vp.width === 360)) {
          const buttons = await page.locator('button, [role=button], a.fab, .fab').all()
          const cand = []
          for (const b of buttons) {
            if (!(await b.isVisible().catch(() => false))) continue
            const name = ((await b.getAttribute('aria-label')) || (await b.getAttribute('title')) || (await b.innerText()) || '').trim()
            const cls = (await b.getAttribute('class')) || ''
            if (DANGER_RE.test(name)) continue
            if (OPEN_RE.test(name) || /fab|add/.test(cls)) cand.push({ name, cls })
          }
          const uniq = [...new Map(cand.map(x => [x.name + '|' + x.cls, x])).values()].slice(0, 8)
          for (const cnd of uniq) {
            const loc = cnd.name
              ? page.locator('button, [role=button], .fab').filter({ hasText: cnd.name }).or(page.locator(`[aria-label="${cnd.name.replace(/"/g, '\\"')}"]`)).first()
              : page.locator(`button[class="${cnd.cls}"]`).first()
            if (!(await loc.isVisible().catch(() => false))) continue
            await loc.click({ timeout: 2000 }).catch(() => {})
            await page.waitForTimeout(400)
            const opened = await page.locator('[role=dialog], .sheet, .more-sheet, .dialog-overlay, .sheet-overlay, .dialog-backdrop').first().isVisible().catch(() => false)
            if (opened) {
              await record('dialog-' + (cnd.name || cnd.cls), { overlay: true })
              // Bildschirmtastatur: reduzierte Höhe
              await page.setViewportSize({ width: KEYBOARD.width, height: KEYBOARD.height })
              await page.waitForTimeout(200)
              const res = await page.evaluate(auditInPage, { insets: KEYBOARD.insets, vw: KEYBOARD.width, vh: KEYBOARD.height, scopeOverlay: true })
              for (const f of res) all.push({ route: route.name || route.path, state: 'dialog-' + (cnd.name || cnd.cls), viewport: KEYBOARD.name, theme: c.theme, locale: c.locale, ...f })
              if (c.vp.width === 390 && c.shots) await page.screenshot({ path: path.join(OUT, `${base}--dialog-${slug(cnd.name || cnd.cls)}--kb.png`) })
              await page.setViewportSize({ width: c.vp.width, height: c.vp.height })
            }
            await page.goto(BASE + route.path)
            await settle(page)
          }
        }
        // Routenspezifische Zustände (nur Light, DE + EN@360)
        const extra = EXTRA[route.name || route.path] || []
        if (c.theme === 'light' && (c.locale === 'de' || c.vp.width === 360)) {
          for (const [name, clicks, overlay] of extra) {
            let ok = true
            for (const sel of clicks) {
              const loc = page.locator(sel).first()
              if (!(await loc.isVisible().catch(() => false))) { ok = false; break }
              await loc.click({ timeout: 2000 }).catch(() => { ok = false })
              await page.waitForTimeout(500)
            }
            if (!ok) { console.log('  extra nicht erreichbar:', route.path, name); await page.goto(BASE + route.path); await settle(page); continue }
            await record(name, { overlay })
            if (overlay) {
              await page.setViewportSize({ width: KEYBOARD.width, height: KEYBOARD.height })
              await page.waitForTimeout(200)
              const res = await page.evaluate(auditInPage, { insets: KEYBOARD.insets, vw: KEYBOARD.width, vh: KEYBOARD.height, scopeOverlay: true })
              for (const f of res) all.push({ route: route.name || route.path, state: name, viewport: KEYBOARD.name, theme: c.theme, locale: c.locale, ...f })
              if (c.vp.width === 390 && c.shots) await page.screenshot({ path: path.join(OUT, `${base}--${name}--kb.png`) })
              await page.setViewportSize({ width: c.vp.width, height: c.vp.height })
            }
            await page.goto(BASE + route.path)
            await settle(page)
          }
        }
      }
      // More-Sheet
      if (user === USER) {
        await page.goto(BASE + '/dashboard'); await settle(page)
        const more = page.locator('.bottom-nav button').last()
        if (await more.isVisible().catch(() => false)) {
          await more.click(); await page.waitForTimeout(400)
          const res = await page.evaluate(auditInPage, { insets: c.vp.insets, vw: c.vp.width, vh: c.vp.height, scopeOverlay: true })
          for (const f of res) all.push({ route: 'more-sheet', state: 'open', viewport: c.vp.name, theme: c.theme, locale: c.locale, ...f })
          if (c.shots) await page.screenshot({ path: path.join(OUT, `more-sheet__${c.vp.name}_${c.theme}_${c.locale}.png`) })
          // niedrige Höhe (kleines Gerät / Tastatur)
          await page.setViewportSize({ width: KEYBOARD.width, height: KEYBOARD.height })
          await page.waitForTimeout(200)
          const resKb = await page.evaluate(auditInPage, { insets: KEYBOARD.insets, vw: KEYBOARD.width, vh: KEYBOARD.height, scopeOverlay: true })
          for (const f of resKb) all.push({ route: 'more-sheet', state: 'open', viewport: KEYBOARD.name, theme: c.theme, locale: c.locale, ...f })
          await page.setViewportSize({ width: c.vp.width, height: c.vp.height })
        }
      }
      await context.close()
    }
    console.log('done', c.vp.name, c.theme, c.locale, all.length)
  }
  await browser.close()
  fs.writeFileSync(path.join(OUT, 'findings.json'), JSON.stringify(all, null, 1))
  // Zusammenfassung: eindeutige Befunde (Typ+Signatur+Route)
  const uniq = new Map()
  for (const f of all) {
    const k = `${f.type}|${f.route}|${f.sig}`
    const u = uniq.get(k) || { ...f, viewports: new Set(), states: new Set(), locales: new Set() }
    u.viewports.add(f.viewport); u.states.add(f.state); u.locales.add(f.locale)
    uniq.set(k, u)
  }
  const lines = [...uniq.values()].sort((a, b) => a.type.localeCompare(b.type) || a.route.localeCompare(b.route))
    .map(u => `${u.type}\t${u.route}\t${[...u.states].slice(0, 3).join(',')}\t${[...u.viewports].join(',')}\t${[...u.locales].join(',')}\t${u.sig}\t„${u.text}“\t${u.detail}`)
  fs.writeFileSync(path.join(OUT, 'summary.tsv'), lines.join('\n') + '\n')
  console.log(`${uniq.size} eindeutige Befunde → ${path.join(OUT, 'summary.tsv')}`)
}

main().catch(e => { console.error(e); process.exit(1) })
