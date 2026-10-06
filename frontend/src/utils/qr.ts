/**
 * QR-Codes clientseitig erzeugen (qrcode-generator, ohne Abhängigkeiten,
 * kein CDN). Ausgabe als SVG-Data-URL für <img> — erlaubt durch
 * `img-src data:` der CSP, kein Inline-Markup im DOM.
 */
import qrcode from 'qrcode-generator'

export function qrSvg(text: string): string {
  // Fehlerkorrektur M (~15 %): robust genug für gedruckte Sticker, URL bleibt klein
  const qr = qrcode(0, 'M')
  qr.addData(text)
  qr.make()
  return qr.createSvgTag({ cellSize: 8, margin: 4, scalable: true })
}

export function qrSvgDataUrl(text: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(qrSvg(text))}`
}
