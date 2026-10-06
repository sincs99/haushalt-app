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
      // Knapp unter dem erreichten Stand (65,4 % Stmts / 65,0 % Lines): fällt die Abdeckung, wird die CI rot.
      thresholds: { statements: 62, lines: 62, functions: 54, branches: 54 },
    },
  },
})
