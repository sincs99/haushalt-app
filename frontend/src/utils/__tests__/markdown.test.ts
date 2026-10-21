import { describe, expect, it } from 'vitest'
import { fillPlaceholders, renderMarkdown } from '../markdown'

describe('renderMarkdown', () => {
  it('rendert Überschriften, Absätze und Listen', () => {
    const html = renderMarkdown('# Titel\n\nEin Absatz\nmit Umbruch.\n\n- eins\n- zwei\n\n## Sub')
    expect(html).toBe('<h1>Titel</h1>\n<p>Ein Absatz<br>mit Umbruch.</p>\n<ul>\n<li>eins</li>\n<li>zwei</li>\n</ul>\n<h2>Sub</h2>')
  })

  it('escaped HTML und erlaubt nur sichere Links', () => {
    const html = renderMarkdown('<script>x</script> [ok](https://example.com) [bad](javascript:alert(1)) **fett**')
    expect(html).toContain('&lt;script&gt;x&lt;/script&gt;')
    expect(html).toContain('<a href="https://example.com" target="_blank" rel="noopener noreferrer">ok</a>')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('<strong>fett</strong>')
  })

  it('rendert mailto-Links ohne target', () => {
    expect(renderMarkdown('[Mail](mailto:a@b.ch)')).toBe('<p><a href="mailto:a@b.ch">Mail</a></p>')
  })
})

describe('fillPlaceholders', () => {
  it('ersetzt bekannte Platzhalter und leert unbekannte', () => {
    expect(fillPlaceholders('{{operator.name}} / {{ nope }}', { 'operator.name': 'Muster GmbH' })).toBe('Muster GmbH / ')
  })
})
