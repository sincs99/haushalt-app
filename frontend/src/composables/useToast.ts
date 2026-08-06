import { ref, readonly } from 'vue'

export interface ToastMessage {
  id: number
  text: string
  type: 'error' | 'success' | 'info'
}

const toasts = ref<ToastMessage[]>([])
let nextId = 0

function showToast(
  text: string,
  type: ToastMessage['type'] = 'error',
  duration = 4000,
) {
  const id = nextId++
  toasts.value.push({ id, text, type })
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }, duration)
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    showToast,
  }
}
