import { ref, readonly } from 'vue'

export interface ToastAction {
  label: string
  onAction: () => void
}

export interface ToastMessage {
  id: number
  text: string
  type: 'error' | 'success' | 'info'
  action?: ToastAction
}

const toasts = ref<ToastMessage[]>([])
let nextId = 0

function showToast(
  text: string,
  type: ToastMessage['type'] = 'error',
  duration?: number,
  action?: ToastAction,
) {
  const id = nextId++
  // Action-Toasts haben 6000ms, normale 4000ms
  const effectiveDuration = duration ?? (action ? 6000 : 4000)
  toasts.value.push({ id, text, type, action })
  const timer = setTimeout(() => {
    dismissToast(id)
  }, effectiveDuration)

  // Rückgabe einer dismiss-Funktion (optional nutzbar)
  return () => {
    clearTimeout(timer)
    dismissToast(id)
  }
}

function dismissToast(id: number) {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    showToast,
    dismissToast,
  }
}
