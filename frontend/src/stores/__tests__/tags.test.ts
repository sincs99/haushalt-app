import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { TagInfo } from '../../types'

const { repo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(),
    fetchTargets: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    regenerateToken: vi.fn(),
    remove: vi.fn(),
    resolve: vi.fn(),
    execute: vi.fn(),
  },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../../repositories/tagsRepository', () => ({
  createOnlineTagsRepository: () => repo,
}))

import { useTagsStore } from '../tags'

function tag(over: Partial<TagInfo> = {}): TagInfo {
  return {
    id: 't1',
    household_id: 'h1',
    token: 'tok-1',
    label: 'Futternapf',
    target_type: 'pet',
    target_id: 'p1',
    target_name: 'Mia',
    target_missing: false,
    action: 'pet.feed',
    created_by_user_id: 'u1',
    created_at: '2026-10-01T00:00:00Z',
    last_used_at: null,
    use_count: 0,
    enabled: true,
    ...over,
  }
}

describe('tags store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    auth.currentHouseholdId = 'h1'
  })

  it('fetchTags lädt die Tags des aktuellen Haushalts', async () => {
    repo.fetchAll.mockResolvedValue([tag()])
    const store = useTagsStore()
    await store.fetchTags()
    expect(repo.fetchAll).toHaveBeenCalledWith('h1')
    expect(store.items).toHaveLength(1)
    expect(store.loading).toBe(false)
  })

  it('ohne Haushalt passiert nichts', async () => {
    auth.currentHouseholdId = null
    const store = useTagsStore()
    await store.fetchTags()
    await store.createTag({ label: 'x', target_type: 'pet', target_id: null, action: 'pet.feed' })
    expect(repo.fetchAll).not.toHaveBeenCalled()
    expect(repo.create).not.toHaveBeenCalled()
  })

  it('sortedTags sortiert nach Bezeichnung', () => {
    const store = useTagsStore()
    store.items = [tag({ id: 'a', label: 'Zimmer' }), tag({ id: 'b', label: 'Bad' })]
    expect(store.sortedTags.map((t) => t.label)).toEqual(['Bad', 'Zimmer'])
  })

  it('createTag übernimmt den Server-Tag (Token kommt vom Server)', async () => {
    repo.create.mockResolvedValue(tag({ token: 'server-token' }))
    const store = useTagsStore()
    const created = await store.createTag({ label: 'Futternapf', target_type: 'pet', target_id: 'p1', action: 'pet.feed' })
    expect(created?.token).toBe('server-token')
    expect(store.items).toHaveLength(1)
  })

  it('createTag ist robust gegen ein schnelleres Socket-Event', async () => {
    const store = useTagsStore()
    repo.create.mockImplementation(async () => {
      store.handleTagCreated(tag())
      return tag()
    })
    await store.createTag({ label: 'Futternapf', target_type: 'pet', target_id: 'p1', action: 'pet.feed' })
    expect(store.items).toHaveLength(1)
  })

  it('setEnabled ist optimistisch und übernimmt die Server-Antwort', async () => {
    const store = useTagsStore()
    store.items = [tag()]
    let resolveUpdate!: (v: TagInfo) => void
    repo.update.mockReturnValue(new Promise((r) => (resolveUpdate = r)))
    const pending = store.setEnabled('t1', false)
    expect(store.items[0].enabled).toBe(false)
    resolveUpdate(tag({ enabled: false, label: 'Server' }))
    await pending
    expect(repo.update).toHaveBeenCalledWith('h1', 't1', { enabled: false })
    expect(store.items[0].label).toBe('Server')
  })

  it('updateTag rollt bei Fehler zurück', async () => {
    const store = useTagsStore()
    store.items = [tag()]
    repo.update.mockRejectedValue(new Error('403'))
    await expect(store.updateTag('t1', { label: 'Neu', enabled: false })).rejects.toThrow('403')
    expect(store.items[0].label).toBe('Futternapf')
    expect(store.items[0].enabled).toBe(true)
  })

  it('regenerateToken ersetzt den Token', async () => {
    const store = useTagsStore()
    store.items = [tag()]
    repo.regenerateToken.mockResolvedValue(tag({ token: 'neu' }))
    await store.regenerateToken('t1')
    expect(store.items[0].token).toBe('neu')
  })

  it('deleteTag entfernt optimistisch und stellt bei Fehler an gleicher Stelle wieder her', async () => {
    const store = useTagsStore()
    store.items = [tag({ id: 'a' }), tag({ id: 'b' }), tag({ id: 'c' })]
    repo.remove.mockRejectedValue(new Error('fail'))
    await expect(store.deleteTag('b')).rejects.toThrow('fail')
    expect(store.items.map((t) => t.id)).toEqual(['a', 'b', 'c'])

    repo.remove.mockResolvedValue(undefined)
    await store.deleteTag('b')
    expect(store.items.map((t) => t.id)).toEqual(['a', 'c'])
  })

  it('Socket-Handler: Upsert, Delete, fremde Haushalte ignorieren', () => {
    const store = useTagsStore()
    store.handleTagCreated(tag())
    store.handleTagUpdated(tag({ use_count: 3 }))
    expect(store.items).toHaveLength(1)
    expect(store.items[0].use_count).toBe(3)

    store.handleTagCreated(tag({ id: 'fremd', household_id: 'h2' }))
    store.handleTagUpdated(tag({ id: 'fremd2', household_id: 'h2' }))
    expect(store.items).toHaveLength(1)

    store.handleTagDeleted({ id: 't1' })
    expect(store.items).toHaveLength(0)
  })

  it('resolveToken/executeToken reichen an das Repository durch', async () => {
    repo.resolve.mockResolvedValue({ tag_id: 't1' })
    repo.execute.mockResolvedValue({ changed: true })
    const store = useTagsStore()
    await store.resolveToken('tok')
    await store.executeToken('tok', { slot: 'evening' })
    expect(repo.resolve).toHaveBeenCalledWith('tok')
    expect(repo.execute).toHaveBeenCalledWith('tok', { slot: 'evening' })
  })

  it('$reset leert den Zustand', () => {
    const store = useTagsStore()
    store.items = [tag()]
    store.targets = [{ target_type: 'pet', actions: [], options: [] }]
    store.$reset()
    expect(store.items).toEqual([])
    expect(store.targets).toEqual([])
  })
})
