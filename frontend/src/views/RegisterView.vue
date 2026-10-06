<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { computed, ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { isValidEmail, PASSWORD_MIN_LENGTH, useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import { errorText } from '../composables/useToast'
import { PhHouse } from '@phosphor-icons/vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t } = useI18n()

// Registrierungs-Modus: 'create' oder 'join'
const mode = ref<'create' | 'join'>('create')

const email = ref('')
const password = ref('')
const displayName = ref('')
const householdName = ref('')
const inviteCode = ref('')
const error = ref('')
const isLoading = ref(false)
const submitted = ref(false)
const formRef = ref<HTMLFormElement | null>(null)

/** Nur interne Pfade als Weiterleitung akzeptieren (kein Open Redirect) */
const redirect = computed(() => {
  const value = route.query.redirect
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : undefined
})
// ?redirect beim Wechsel zum Login mitnehmen (z. B. Tag-Scan)
const loginLink = computed(() => ({ path: '/login', query: redirect.value ? { redirect: redirect.value } : {} }))

// Inline-Validierung (erst nach dem ersten Absenden), statt englischer Backend-Meldungen
const emailError = computed(() => {
  if (!submitted.value) return undefined
  if (!email.value.trim()) return t('auth.emailRequired')
  if (!isValidEmail(email.value)) return t('auth.emailInvalid')
  return undefined
})
const passwordError = computed(() => {
  if (!submitted.value) return undefined
  if (!password.value) return t('auth.passwordRequired')
  if (password.value.length < PASSWORD_MIN_LENGTH) return t('auth.passwordTooShort')
  return undefined
})
const displayNameError = computed(() =>
  submitted.value && !displayName.value.trim() ? t('auth.displayNameRequired') : undefined,
)
const householdNameError = computed(() =>
  submitted.value && mode.value === 'create' && !householdName.value.trim() ? t('auth.householdNameRequired') : undefined,
)
const inviteCodeError = computed(() =>
  submitted.value && mode.value === 'join' && !inviteCode.value.trim() ? t('auth.inviteCodeRequired') : undefined,
)
const hasErrors = computed(() =>
  !!(emailError.value || passwordError.value || displayNameError.value || householdNameError.value || inviteCodeError.value),
)

onMounted(() => {
  // Autofokus auf das erste Feld (E-Mail)
  formRef.value?.querySelector('input')?.focus()

  // Query-Parameter ?code=XYZ → automatisch Beitreten-Modus
  const code = route.query.code
  if (typeof code === 'string' && code.trim()) {
    mode.value = 'join'
    inviteCode.value = code.trim().toUpperCase()
  }
})

async function handleRegister() {
  error.value = ''
  submitted.value = true
  if (hasErrors.value) return
  isLoading.value = true
  const mail = email.value.trim()
  const name = displayName.value.trim()
  try {
    if (mode.value === 'create') {
      await authStore.register(mail, password.value, name, { householdName: householdName.value.trim() })
    } else {
      await authStore.register(mail, password.value, name, { inviteCode: inviteCode.value.trim().toUpperCase() })
    }
    router.push(redirect.value || '/dashboard')
  } catch (err: any) {
    error.value = errorText(t('auth.registerFailed'), err)
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <BaseCard padding="lg" class="auth-card">
      <h1 class="auth-title"><PhHouse :size="24" /> {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('auth.registerSubtitle') }}</p>

      <!-- Tab-Umschalter -->
      <div class="register-tabs">
        <button
          type="button"
          class="register-tab"
          :aria-pressed="mode === 'create'"
          :class="{ 'register-tab--active': mode === 'create' }"
          @click="mode = 'create'"
        >
          {{ $t('auth.tabCreate') }}
        </button>
        <button
          type="button"
          class="register-tab"
          :aria-pressed="mode === 'join'"
          :class="{ 'register-tab--active': mode === 'join' }"
          @click="mode = 'join'"
        >
          {{ $t('auth.tabJoin') }}
        </button>
      </div>

      <form ref="formRef" novalidate @submit.prevent="handleRegister" class="auth-form">
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
          :placeholder="$t('auth.passwordMinLength')"
          autocomplete="new-password"
          :error="passwordError"
        />
        <BaseInput
          v-model="displayName"
          :label="$t('auth.displayName')"
          type="text"
          :placeholder="$t('auth.namePlaceholder')"
          autocomplete="name"
          maxlength="100"
          :error="displayNameError"
        />

        <!-- Modus-spezifische Felder -->
        <BaseInput
          v-if="mode === 'create'"
          v-model="householdName"
          :label="$t('auth.householdName')"
          type="text"
          :placeholder="$t('auth.householdPlaceholder')"
          maxlength="100"
          :error="householdNameError"
        />
        <BaseInput
          v-if="mode === 'join'"
          v-model="inviteCode"
          :label="$t('auth.inviteCodeLabel')"
          type="text"
          :placeholder="$t('auth.inviteCodePlaceholder')"
          autocapitalize="characters"
          autocomplete="off"
          style="text-transform: uppercase"
          :error="inviteCodeError"
        />

        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>

        <BaseButton type="submit" variant="primary" :loading="isLoading" :disabled="isLoading" class="auth-submit">
          {{ $t('auth.register') }}
        </BaseButton>

        <p class="auth-link">
          {{ $t('auth.hasAccount') }} <router-link :to="loginLink">{{ $t('auth.loginHere') }}</router-link>
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

.register-tabs {
  display: flex;
  gap: var(--space-1);
  margin-bottom: var(--space-4);
  background: var(--color-neutral-100);
  border-radius: var(--radius-md);
  padding: var(--space-1);
}

.register-tab {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-family: var(--font-family);
  transition: all 0.15s ease;
}

.register-tab--active {
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: var(--shadow-sm);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
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
