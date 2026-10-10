/**
 * Ein anderes Mitglied hat den aktuellen Haushalt verlassen oder wurde entfernt.
 *
 * Der Server gibt dabei dessen offene Zuständigkeiten frei (PD-H1): offene Aufgaben,
 * Einkaufsartikel und Ämtli-Termine → niemand, Rotation ohne die Person, Standard-Zahler
 * wiederkehrender Rechnungen → leer, Stimmen in offenen Umfragen gelöscht. Dafür kommen
 * keine Einzel-Events — das Event `household_member_left`/`_removed` nennt in `released`
 * die betroffenen Bereiche, und die Stores laden diese hier neu.
 *
 * Ohne `released` (älterer Server) werden alle Bereiche neu geladen.
 */
export type ReleasedArea = 'todos' | 'shopping' | 'chores' | 'recurring_bills' | 'polls'

const ALL_AREAS: ReleasedArea[] = ['todos', 'shopping', 'chores', 'recurring_bills', 'polls']

export async function refetchAfterMemberDeparture(released?: string[] | null): Promise<void> {
  const areas = new Set(Array.isArray(released) ? released : ALL_AREAS)
  // Fehler bewusst verschlucken: die Ansichten zeigen ihren eigenen Fehlerzustand
  const quiet = (p: Promise<unknown> | void) => { if (p) p.catch(() => {}) }

  const [{ useTodosStore }, { useShoppingStore }, { useChoresStore }, { useFinanceStore }, { usePollsStore }, { useDashboardStore }] =
    await Promise.all([
      import('../stores/todos'),
      import('../stores/shopping'),
      import('../stores/chores'),
      import('../stores/finance'),
      import('../stores/polls'),
      import('../stores/dashboard'),
    ])

  // Mitgliederlisten (Zuweisungs-Auswahl) sind in jedem Fall veraltet
  quiet(useTodosStore().fetchMembers())
  quiet(useChoresStore().fetchMembers())

  if (areas.has('todos')) quiet(useTodosStore().fetchTodos())
  if (areas.has('shopping')) quiet(useShoppingStore().fetchItems())
  if (areas.has('chores')) {
    quiet(useChoresStore().fetchChores())
    quiet(useChoresStore().fetchAssignments())
  }
  if (areas.has('recurring_bills')) {
    quiet(useFinanceStore().fetchBills())
    quiet(useFinanceStore().fetchSummary())
  }
  if (areas.has('polls')) quiet(usePollsStore().fetchPolls('offen'))
  useDashboardStore().invalidate()

  // Freigegebenes zählt jetzt für alle → Zahl am App-Icon neu berechnen
  const { refreshAppBadgeSoon } = await import('../composables/useAppBadge')
  refreshAppBadgeSoon()
}
