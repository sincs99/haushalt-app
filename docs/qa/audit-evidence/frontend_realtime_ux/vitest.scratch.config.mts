import { defineConfig } from '/home/user/haushalt-app/frontend/node_modules/vitest/dist/config.js'
export default defineConfig({
  root: '<scratchpad>/work/frontend_realtime_ux',
  resolve: { alias: {
    pinia: '/home/user/haushalt-app/frontend/node_modules/pinia',
    vue: '/home/user/haushalt-app/frontend/node_modules/vue',
  } },
  server: { fs: { allow: ['<scratchpad>/work/frontend_realtime_ux', '/home/user/haushalt-app/frontend'] } },
  test: {
    globals: true,
    environment: 'node',
    include: ['<scratchpad>/work/frontend_realtime_ux/*.test.ts'],
    setupFiles: ['/home/user/haushalt-app/frontend/src/test/setup.ts'],
  },
})
