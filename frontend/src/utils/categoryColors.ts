import type { EventCategory } from '../types'

export const categoryColors: Record<EventCategory, string> = {
  arbeit:      '#5B8DEF',
  katzen:      '#F4A261',
  haushalt:    '#6E9273',
  freunde:     '#9C6E79',
  geburtstage: '#E76F51',
  essen:       '#C09A62',
  sonstiges:   '#8B8B8B',
}

export const categoryLabels: Record<EventCategory, string> = {
  arbeit:      'Arbeit',
  katzen:      'Katzen',
  haushalt:    'Haushalt',
  freunde:     'Freunde',
  geburtstage: 'Geburtstage',
  essen:       'Essen',
  sonstiges:   'Sonstiges',
}

export const ALL_CATEGORIES: EventCategory[] = [
  'arbeit', 'katzen', 'haushalt', 'freunde', 'geburtstage', 'essen', 'sonstiges',
]
