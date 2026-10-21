
export default ({
  root: '/home/user/haushalt-app/frontend',
  test: { globals: true, environment: 'node', include: ['<scratchpad>/work/shopping_food_calendar/vt/*.test.ts'], setupFiles: ['/home/user/haushalt-app/frontend/src/test/setup.ts'] },
  server: { fs: { allow: ['/home/user/haushalt-app/frontend', '<scratchpad>/work/shopping_food_calendar'] } },
})
