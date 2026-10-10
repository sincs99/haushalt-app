import { defineConfig } from '/home/user/haushalt-app/frontend/node_modules/vitest/dist/config.js'
export default defineConfig({
  root: '/home/user/haushalt-app/frontend',
  cacheDir: '<scratchpad>/work/finance/vt/.cache',
  test: { environment: 'node', include: ['<scratchpad>/work/finance/vt/**/*.test.ts'], setupFiles: ['/home/user/haushalt-app/frontend/src/test/setup.ts'], server: { deps: { inline: true } } },
})
