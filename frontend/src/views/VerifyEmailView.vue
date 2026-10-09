<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseSpinner from '../components/ui/BaseSpinner.vue'
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PhHouse } from '@phosphor-icons/vue'
import { useAuthStore } from '../stores/auth'
import { accountRepository } from '../repositories/accountRepository'
import { errorText } from '../composables/useToast'

/**
 * Ziel des Bestätigungs-Links aus der E-Mail (/verify-email?token=…). Kein Login nötig:
 * Der Token allein beweist den Zugriff auf das Postfach.
 */
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()

const state = ref<'pending' | 'done' | 'error'>('pending')
const error = ref('')

onMounted(async () => {
  const token = typeof route.query.token === 'string' ? route.query.token : ''
  if (!token) {
    state.value = 'error'
    error.value = t('account.linkInvalidMessage')
    return
  }
  try {
    await accountRepository.verifyEmail(token)
    authStore.markEmailVerified()
    state.value = 'done'
  } catch (err) {
    state.value = 'error'
    error.value = errorText(t('account.verifyFailed'), err)
  }
})

function continueToApp() {
  router.replace(authStore.isAuthenticated ? '/dashboard' : '/login')
}
</script>

<template>
  <div class="auth-page">
    <BaseCard padding="lg" class="auth-card">
      <h1 class="auth-title"><PhHouse :size="24" /> {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('account.verifyTitle') }}</p>

      <div v-if="state === 'pending'" class="auth-info" role="status">
        <BaseSpinner size="sm" /> {{ $t('common.loading') }}
      </div>
      <div v-else-if="state === 'done'" class="auth-info" role="status">
        <strong>{{ $t('account.verifyDoneTitle') }}</strong>
        <span>{{ $t('account.verifyDoneMessage') }}</span>
      </div>
      <div v-else class="auth-info" role="alert">
        <strong>{{ $t('account.linkInvalidTitle') }}</strong>
        <span>{{ error }}</span>
      </div>

      <BaseButton v-if="state !== 'pending'" variant="primary" class="auth-submit" @click="continueToApp">
        {{ authStore.isAuthenticated ? $t('account.continueToApp') : $t('auth.login') }}
      </BaseButton>
    </BaseCard>
  </div>
</template>

<style scoped src="../assets/auth.css"></style>
