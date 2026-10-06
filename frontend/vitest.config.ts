import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/utils/**', 'src/stores/**', 'src/repositories/**'],
      exclude: ['**/__tests__/**'],
      reporter: ['text-summary', 'text'],
    },
  },
})
