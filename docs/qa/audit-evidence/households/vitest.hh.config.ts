import { defineConfig } from '/home/user/haushalt-app/frontend/node_modules/vitest/dist/config.js'
export default defineConfig({
  root: '/home/user/haushalt-app/frontend',
  resolve: { alias: { pinia: '/home/user/haushalt-app/frontend/node_modules/pinia', vue: '/home/user/haushalt-app/frontend/node_modules/vue' } },
  server: { fs: { allow: ['/home/user/haushalt-app/frontend', '<scratchpad>/work/households'] } },
  test: { globals: true, environment: 'node', include: ['<scratchpad>/work/households/**/*.test.ts'], setupFiles: ['/home/user/haushalt-app/frontend/src/test/setup.ts'] },
})
