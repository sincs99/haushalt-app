/** Browser state belongs to one login and one selected household, not to a JWT. */
let sessionGeneration = 0
let dataGeneration = 0
let requests = new AbortController()

export class ScopeChangedError extends Error {
  readonly code = 'ERR_CANCELED'
  constructor() { super('The session or household changed'); this.name = 'ScopeChangedError' }
}

export const currentSessionGeneration = () => sessionGeneration
export const currentDataGeneration = () => dataGeneration
export const currentScopeSignal = () => requests.signal

export function invalidateDataScope(): void {
  dataGeneration++
  requests.abort()
  requests = new AbortController()
}

export function invalidateSessionScope(): void {
  sessionGeneration++
  invalidateDataScope()
}

export function assertSessionGeneration(generation: number): void {
  if (generation !== sessionGeneration) throw new ScopeChangedError()
}

export function assertDataGeneration(generation: number): void {
  if (generation !== dataGeneration) throw new ScopeChangedError()
}

export function isScopeChanged(error: unknown): boolean {
  return error instanceof ScopeChangedError
}

/** Also guards repository mocks/offline implementations and optimistic rollback paths. */
export function scopeRepository<T extends object>(repository: T): T {
  return new Proxy(repository, {
    get(target, key, receiver) {
      const method = Reflect.get(target, key, receiver)
      if (typeof method !== 'function') return method
      return async (...args: unknown[]) => {
        const generation = dataGeneration
        try {
          const result = await method.apply(target, args)
          assertDataGeneration(generation)
          return result
        } catch (error) {
          assertDataGeneration(generation)
          throw error
        }
      }
    },
  })
}
