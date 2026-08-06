import { ref, readonly } from 'vue'

const isOnline = ref<boolean>(navigator.onLine)

window.addEventListener('online', () => {
  isOnline.value = true
})

window.addEventListener('offline', () => {
  isOnline.value = false
})

export function useConnectivity() {
  return {
    isOnline: readonly(isOnline),
  }
}
