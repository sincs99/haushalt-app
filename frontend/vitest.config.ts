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
      // Knapp unter dem erreichten Stand: fällt die Abdeckung, wird die CI rot.
      thresholds: { statements: 66, lines: 66, functions: 57, branches: 59 },
    },
  },
})
