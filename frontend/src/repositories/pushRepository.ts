import api from '../api/client'

export interface PushConfig {
  enabled: boolean
  public_key: string | null
}

export interface PushSubscriptionPayload {
  endpoint: string
  keys: { p256dh: string; auth: string }
  locale: string
}

export interface PushRepository {
  fetchConfig(): Promise<PushConfig>
  subscribe(payload: PushSubscriptionPayload): Promise<void>
  unsubscribe(endpoint: string): Promise<void>
  sendTest(): Promise<{ sent: number }>
}

export function createOnlinePushRepository(): PushRepository {
  return {
    async fetchConfig() {
      const { data } = await api.get<PushConfig>('/api/push/config')
      return data
    },
    async subscribe(payload) {
      await api.post('/api/push/subscriptions', payload)
    },
    async unsubscribe(endpoint) {
      await api.delete('/api/push/subscriptions', { data: { endpoint } })
    },
    async sendTest() {
      const { data } = await api.post<{ sent: number }>('/api/push/test')
      return data
    },
  }
}
