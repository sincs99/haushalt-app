<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()

const email = ref('')
const password = ref('')
const error = ref('')
const isLoading = ref(false)

async function handleLogin() {
  error.value = ''
  isLoading.value = true
  try {
    await authStore.login(email.value, password.value)
    router.push('/shopping')
  } catch (err: any) {
    error.value =
      err.response?.data?.detail || t('auth.loginFailed')
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <BaseCard padding="lg" class="auth-card">
      <h1 class="auth-title">🏠 {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('auth.loginSubtitle') }}</p>

      <form @submit.prevent="handleLogin" class="auth-form">
        <BaseInput
          v-model="email"
          :label="$t('auth.email')"
          type="email"
          :placeholder="$t('auth.emailPlaceholder')"
          autocomplete="email"
          :error="error && !email ? $t('auth.emailRequired') : undefined"
        />

        <BaseInput
          v-model="password"
          :label="$t('auth.password')"
          type="password"
          :placeholder="$t('auth.password')"
          autocomplete="current-password"
        />

        <p v-if="error" class="auth-error">{{ error }}</p>

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
          {{ $t('auth.noAccount') }} <router-link to="/register">{{ $t('auth.register') }}</router-link>
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
  font-size: var(--text-xl);
  font-weight: var(--font-weight-bold);
  text-align: center;
  color: var(--color-text);
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

.auth-error {
  margin: 0;
  padding: var(--space-3);
  background: #FEF2F2;
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
