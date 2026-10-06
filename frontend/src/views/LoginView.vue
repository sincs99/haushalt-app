<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isValidEmail, useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import { errorText } from '../composables/useToast'
import { PhHouse } from '@phosphor-icons/vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t } = useI18n()

const email = ref('')
const password = ref('')
const error = ref('')
const isLoading = ref(false)
const submitted = ref(false)

/** Nur interne Pfade als Weiterleitung akzeptieren (kein Open Redirect) */
const redirect = computed(() => {
  const value = route.query.redirect
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : undefined
})
// ?redirect beim Wechsel zur Registrierung mitnehmen (z. B. Tag-Scan als Neuling)
const registerLink = computed(() => ({ path: '/register', query: redirect.value ? { redirect: redirect.value } : {} }))

// Inline-Validierung erst nach dem ersten Absenden anzeigen
const emailError = computed(() => {
  if (!submitted.value) return undefined
  if (!email.value.trim()) return t('auth.emailRequired')
  if (!isValidEmail(email.value)) return t('auth.emailInvalid')
  return undefined
})
const passwordError = computed(() => (submitted.value && !password.value ? t('auth.passwordRequired') : undefined))

// Autofokus auf das E-Mail-Feld (das HTML-Attribut greift bei SPA-Navigation nicht zuverlässig)
const formRef = ref<HTMLFormElement | null>(null)
onMounted(() => formRef.value?.querySelector('input')?.focus())

async function handleLogin() {
  error.value = ''
  submitted.value = true
  if (emailError.value || passwordError.value) return
  isLoading.value = true
  try {
    await authStore.login(email.value.trim(), password.value)
    // Redirect zur vorher gewünschten Seite oder Startseite
    router.push(redirect.value || '/dashboard')
  } catch (err: any) {
    error.value = errorText(t('auth.loginFailed'), err)
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <BaseCard padding="lg" class="auth-card">
      <h1 class="auth-title"><PhHouse :size="24" /> {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('auth.loginSubtitle') }}</p>

      <div v-if="authStore.sessionExpired" class="auth-info" role="status">
        <strong>{{ $t('auth.sessionExpired') }}</strong>
        <span>{{ $t('auth.sessionExpiredMessage') }}</span>
      </div>

      <form ref="formRef" novalidate @submit.prevent="handleLogin" class="auth-form">
        <BaseInput
          v-model="email"
          :label="$t('auth.email')"
          type="email"
          :placeholder="$t('auth.emailPlaceholder')"
          autocomplete="email"
          inputmode="email"
          autocapitalize="off"
          :error="emailError"
        />

        <BaseInput
          v-model="password"
          :label="$t('auth.password')"
          type="password"
          :placeholder="$t('auth.password')"
          autocomplete="current-password"
          :error="passwordError"
        />

        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>

        <BaseButton
          type="submit"
          variant="primary"
          :loading="isLoading"
          :disabled="isLoading"
          class="auth-submit"
        >
          {{ $t('auth.login') }}
        </BaseButton>

        <p class="auth-link">
          {{ $t('auth.noAccount') }} <router-link :to="registerLink">{{ $t('auth.register') }}</router-link>
        </p>
      </form>
    </BaseCard>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  background: var(--color-bg);
}

.auth-card {
  width: 100%;
  max-width: 400px;
}

.auth-title {
  margin: 0 0 var(--space-1);
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-semibold);
  text-align: center;
  color: var(--ink);
}

.auth-subtitle {
  margin: 0 0 var(--space-6);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-align: center;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.auth-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0 0 var(--space-4);
  padding: var(--space-3);
  background: var(--chip);
  border-radius: var(--radius-sm);
  color: var(--ink);
  font-size: var(--text-sm);
}

.auth-error {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-danger-light);
  border: 1px solid #FECACA;
  border-radius: var(--radius-sm);
  color: var(--color-danger);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
}

.auth-submit {
  width: 100%;
}

.auth-link {
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: 0;
}

.auth-link a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: var(--font-weight-medium);
}

.auth-link a:hover {
  text-decoration: underline;
}
</style>
