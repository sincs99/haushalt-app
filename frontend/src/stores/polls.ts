import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuthStore } from './auth'
import { createOnlinePollsRepository } from '../repositories/pollsRepository'
import type {
  EventPoll,
  PollCreatePayload,
  PollDecidePayload,
} from '../types'

export const usePollsStore = defineStore('polls', () => {
  // Repository
  const repo = createOnlinePollsRepository()

  // State
  const polls = ref<EventPoll[]>([])
  const loading = ref(false)

  // Computed
  const openPolls = computed(() =>
    polls.value.filter(p => p.status === 'offen'),
  )

  const openMealPolls = computed(() =>
    polls.value.filter(p => p.status === 'offen' && p.poll_type === 'meal'),
  )

  // Actions
  async function fetchPolls(status?: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      polls.value = await repo.fetchAll(householdId, status)
    } finally {
      loading.value = false
    }
  }

  async function createPoll(payload: PollCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.create(householdId, payload)
    // Duplikat-Schutz: Socket könnte schneller sein
    const idx = polls.value.findIndex(p => p.id === created.id)
    if (idx !== -1) {
      polls.value[idx] = created
    } else {
      polls.value.push(created)
    }
  }

  async function votePoll(pollId: string, optionId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    const userId = authStore.user?.id
    if (!householdId || !userId) return

    // Optimistic: eigene Stimme sofort markieren
    const poll = polls.value.find(p => p.id === pollId)
    if (!poll) return

    // Snapshot für Rollback
    const snapshot = JSON.parse(JSON.stringify(poll)) as EventPoll

    // Eigene Stimme aus allen Optionen entfernen und in der gewählten setzen
    for (const opt of poll.options) {
      opt.votes = opt.votes.filter(v => v.user_id !== userId)
    }
    const targetOption = poll.options.find(o => o.id === optionId)
    if (targetOption) {
      targetOption.votes.push({
        id: crypto.randomUUID(),
        user_id: userId,
        created_at: new Date().toISOString(),
      })
    }

    try {
      const updated = await repo.vote(householdId, pollId, { option_id: optionId })
      // Server-Antwort übernehmen
      const idx = polls.value.findIndex(p => p.id === pollId)
      if (idx !== -1) {
        polls.value[idx] = updated
      }
    } catch (error) {
      // Rollback
      const idx = polls.value.findIndex(p => p.id === pollId)
      if (idx !== -1) {
        polls.value[idx] = snapshot
      }
      throw error
    }
  }

  async function decidePoll(pollId: string, payload: PollDecidePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.decide(householdId, pollId, payload)
    const idx = polls.value.findIndex(p => p.id === pollId)
    if (idx !== -1) {
      polls.value[idx] = updated
    }
  }

  async function deletePoll(pollId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic: sofort entfernen
    const idx = polls.value.findIndex(p => p.id === pollId)
    if (idx === -1) return
    const removed = polls.value[idx]
    polls.value.splice(idx, 1)

    try {
      await repo.remove(householdId, pollId)
    } catch (error) {
      // Rollback
      polls.value.splice(idx, 0, removed)
      throw error
    }
  }

  async function mealDecidePoll(pollId: string, optionId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.mealDecide(householdId, pollId, { option_id: optionId })
    const idx = polls.value.findIndex(p => p.id === pollId)
    if (idx !== -1) {
      polls.value[idx] = updated
    }
  }

  async function createMealPoll(question: string, mealDate: string, options: Array<{ label: string; recipe_id?: string }>) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const payload: PollCreatePayload = {
      question,
      poll_type: 'meal',
      meal_date: mealDate,
      options: options.map(o => ({ label: o.label, recipe_id: o.recipe_id ?? null })),
    }
    const created = await repo.create(householdId, payload)
    const idx = polls.value.findIndex(p => p.id === created.id)
    if (idx !== -1) {
      polls.value[idx] = created
    } else {
      polls.value.push(created)
    }
  }

  // Socket-Handler — Idempotent
  function handleSocketCreated(poll: EventPoll) {
    const existing = polls.value.findIndex(p => p.id === poll.id)
    if (existing !== -1) {
      polls.value[existing] = poll
    } else {
      polls.value.push(poll)
    }
  }

  function handleSocketVoted(poll: EventPoll) {
    const idx = polls.value.findIndex(p => p.id === poll.id)
    if (idx !== -1) {
      polls.value[idx] = poll
    }
  }

  function handleSocketDecided(poll: EventPoll) {
    const idx = polls.value.findIndex(p => p.id === poll.id)
    if (idx !== -1) {
      polls.value[idx] = poll
    }
  }

  function handleSocketDeleted(data: { id: string }) {
    polls.value = polls.value.filter(p => p.id !== data.id)
  }

  return {
    // State
    polls,
    loading,
    // Computed
    openPolls,
    openMealPolls,
    // Actions
    fetchPolls,
    createPoll,
    votePoll,
    decidePoll,
    deletePoll,
    mealDecidePoll,
    createMealPoll,
    // Socket-Handler
    handleSocketCreated,
    handleSocketVoted,
    handleSocketDecided,
    handleSocketDeleted,
  }
})
