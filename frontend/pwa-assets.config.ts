import { defineConfig, minimal2023Preset } from '@vite-pwa/assets-generator/config'

export default defineConfig({
  headLinkOptions: { preset: '2023' },
  preset: {
    ...minimal2023Preset,
    maskable: { ...minimal2023Preset.maskable, resizeOptions: { background: '#A0714A' } },
    apple: { ...minimal2023Preset.apple, resizeOptions: { background: '#A0714A' } },
  },
  images: ['public/logo.svg'],
})
