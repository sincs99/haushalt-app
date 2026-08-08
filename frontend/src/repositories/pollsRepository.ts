import api from '../api/client'
import type { EventPoll, PollCreatePayload, PollVotePayload, PollDecidePayload, MealDecidePayload } from '../types'

export interface PollsRepository {
  fetchAll(householdId: string, status?: string): Promise<EventPoll[]>
  fetchOne(householdId: string, pollId: string): Promise<EventPoll>
  create(householdId: string, data: PollCreatePayload): Promise<EventPoll>
  vote(householdId: string, pollId: string, data: PollVotePayload): Promise<EventPoll>
  decide(householdId: string, pollId: string, data: PollDecidePayload): Promise<EventPoll>
  mealDecide(householdId: string, pollId: string, data: MealDecidePayload): Promise<EventPoll>
  remove(householdId: string, pollId: string): Promise<void>
}

export function createOnlinePollsRepository(): PollsRepository {
  return {
    async fetchAll(householdId, status) {
      const { data } = await api.get<EventPoll[]>(
        `/api/households/${householdId}/polls/`,
        { params: status ? { status } : {} },
      )
      return data
    },
    async fetchOne(householdId, pollId) {
      const { data } = await api.get<EventPoll>(
        `/api/households/${householdId}/polls/${pollId}`,
      )
      return data
    },
    async create(householdId, payload) {
      const { data } = await api.post<EventPoll>(
        `/api/households/${householdId}/polls/`,
        payload,
      )
      return data
    },
    async vote(householdId, pollId, payload) {
      const { data } = await api.post<EventPoll>(
        `/api/households/${householdId}/polls/${pollId}/vote`,
        payload,
      )
      return data
    },
    async decide(householdId, pollId, payload) {
      const { data } = await api.post<EventPoll>(
        `/api/households/${householdId}/polls/${pollId}/decide`,
        payload,
      )
      return data
    },
    async mealDecide(householdId, pollId, payload) {
      const { data } = await api.post<EventPoll>(
        `/api/households/${householdId}/polls/${pollId}/meal-decide`,
        payload,
      )
      return data
    },
    async remove(householdId, pollId) {
      await api.delete(`/api/households/${householdId}/polls/${pollId}`)
    },
  }
}
