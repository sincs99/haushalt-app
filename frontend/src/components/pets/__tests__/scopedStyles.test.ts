// Die Tier-Detailseite ist auf mehrere Komponenten verteilt. Scoped-Styles wirken nur im
// Template derselben Datei — dieser Test stellt sicher, dass jede Klasse aus einem
// <style scoped>-Block auch im Template derselben Komponente vorkommt (sonst greift die
// Regel still nicht mehr, z. B. nach dem Verschieben von Markup in eine andere Komponente).
// Vitest läuft hier ohne Vue-Plugin/DOM, daher statisch über den SFC-Parser.
import { parse } from 'vue/compiler-sfc'
import { describe, expect, it } from 'vitest'
import PetDetailView from '../../../views/PetDetailView.vue?raw'
import PetAboutCard from '../PetAboutCard.vue?raw'
import PetCareTasksSection from '../PetCareTasksSection.vue?raw'
import PetEditDialog from '../PetEditDialog.vue?raw'
import PetFeedingCard from '../PetFeedingCard.vue?raw'
import PetMedicationFormDialog from '../PetMedicationFormDialog.vue?raw'
import PetMedicationsCard from '../PetMedicationsCard.vue?raw'
import PetProfileHeader from '../PetProfileHeader.vue?raw'

const files: Record<string, string> = {
  PetDetailView,
  PetAboutCard,
  PetCareTasksSection,
  PetEditDialog,
  PetFeedingCard,
  PetMedicationFormDialog,
  PetMedicationsCard,
  PetProfileHeader,
}

function scopedClasses(css: string): string[] {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '')
  // Nur Selektoren (vor „{“), nicht Werte wie „0.92“
  const selectors = withoutComments.match(/[^{}]+(?=\{)/g) ?? []
  const classes = selectors.flatMap(sel => sel.match(/\.[a-zA-Z_][\w-]*/g) ?? []).map(c => c.slice(1))
  return [...new Set(classes)]
}

function usedInTemplate(template: string, cls: string): boolean {
  if (new RegExp(`(^|[^\\w-])${cls}([^\\w-]|$)`).test(template)) return true
  // Dynamisch zusammengesetzt, z. B. :class="'health-dot--' + entry.severity"
  const dash = cls.lastIndexOf('--')
  return dash > 0 && template.includes(`'${cls.slice(0, dash + 2)}'`)
}

describe('Tier-Detailseite: Scoped-Styles passen zum Template', () => {
  it.each(Object.entries(files))('%s', (name, source) => {
    const { descriptor, errors } = parse(source, { filename: `${name}.vue` })
    expect(errors).toEqual([])
    const template = descriptor.template?.content ?? ''
    const css = descriptor.styles.filter(s => s.scoped).map(s => s.content).join('\n')
    expect(css.length).toBeGreaterThan(0)
    const unused = scopedClasses(css).filter(cls => !usedInTemplate(template, cls))
    expect(unused).toEqual([])
  })
})
