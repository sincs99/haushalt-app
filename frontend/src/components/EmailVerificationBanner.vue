<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhEnvelopeSimple } from '@phosphor-icons/vue'
import { useAuthStore } from '../stores/auth'
import { useConfigStore } from '../stores/config'
import { accountRepository } from '../repositories/accountRepository'
import { useToast } from '../composables/useToast'

/**
 * Hinweis für Konten mit unbestätigter E-Mail-Adresse — nur wenn der Server Mails
 * verschicken kann. Die App bleibt nutzbar; der Hinweis lässt sich pro Sitzung schliessen.
 */
const authStore = useAuthStore()
const configStore = useConfigStore()
const { t } = useI18n()
const { notifySuccess, notifyError } = useToast()

const dismissed = ref(false)
const sending = ref(false)

const visible = computed(
  () =>
    !dismissed.value &&
    configStore.config.mail_enabled &&
    authStore.user !== null &&
    authStore.user.email_verified === false,
)

onMounted(() => configStore.load())

async function resend() {
  if (sending.value) return
  sending.value = true
  try {
    await accountRepository.resendVerification()
    notifySuccess(t('account.verifyResent'))
    dismissed.value = true
  } catch (error) {
    notifyError(t('account.verifyResendFailed'), error)
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div v-if="visible" class="verify-banner" role="status">
    <PhEnvelopeSimple :size="18" class="verify-banner__icon" />
    <span class="verify-banner__text">{{ t('account.verifyBanner', { email: authStore.user?.email }) }}</span>
    <button type="button" class="verify-banner__action tap-target" :disabled="sending" @click="resend">
      {{ t('account.verifyResend') }}
    </button>
    <button type="button" class="verify-banner__close tap-target" :aria-label="t('common.close')" @click="dismissed = true">
      ×
    </button>
  </div>
</template>

<style scoped>
.verify-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 var(--space-4) var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--chip);
  border-radius: var(--radius-sm);
  color: var(--ink);
  font-size: var(--text-sm);
}

.verify-banner__icon {
  flex-shrink: 0;
}

.verify-banner__text {
  flex: 1;
  min-width: 0;
}

.verify-banner__action,
.verify-banner__close {
  flex-shrink: 0;
  border: none;
  background: transparent;
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
  font-size: var(--text-sm);
  cursor: pointer;
}

.verify-banner__close {
  color: var(--color-text-secondary);
  font-size: var(--text-lg);
  line-height: 1;
}
</style>
