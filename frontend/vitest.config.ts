import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    include: ['src/**/*.test.ts'],
    setupFiles: ['src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      include: ['src/utils/**', 'src/stores/**', 'src/repositories/**'],
      exclude: ['src/**/__tests__/**', 'src/test/**'],
      reporter: ['text', 'text-summary', 'lcov'],
    },
  },
})
