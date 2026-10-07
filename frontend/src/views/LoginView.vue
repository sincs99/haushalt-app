<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import { translateApiError } from '../utils/apiErrors'
import { PhHouse } from '@phosphor-icons/vue'

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
    // Redirect zur vorher gewünschten Seite oder Default
    const redirect = router.currentRoute.value.query.redirect as string | undefined
    router.push(redirect || '/shopping')
  } catch (err: any) {
    error.value = translateApiError(err)
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

<style scoped src="../assets/auth.css"></style>
