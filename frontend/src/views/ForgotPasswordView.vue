<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhHouse } from '@phosphor-icons/vue'
import { isValidEmail } from '../stores/auth'
import { accountRepository } from '../repositories/accountRepository'
import { errorText } from '../composables/useToast'

const { t } = useI18n()

const email = ref('')
const error = ref('')
const sent = ref(false)
const isLoading = ref(false)
const submitted = ref(false)
const formRef = ref<HTMLFormElement | null>(null)

const emailError = computed(() => {
  if (!submitted.value) return undefined
  if (!email.value.trim()) return t('auth.emailRequired')
  if (!isValidEmail(email.value)) return t('auth.emailInvalid')
  return undefined
})

onMounted(() => formRef.value?.querySelector('input')?.focus())

async function submit() {
  error.value = ''
  submitted.value = true
  if (emailError.value) return
  isLoading.value = true
  try {
    await accountRepository.forgotPassword(email.value.trim())
    sent.value = true
  } catch (err) {
    error.value = errorText(t('account.forgotFailed'), err)
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <BaseCard padding="lg" class="auth-card">
      <h1 class="auth-title"><PhHouse :size="24" /> {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('account.forgotSubtitle') }}</p>

      <div v-if="sent" class="auth-info" role="status">
        <strong>{{ $t('account.forgotSentTitle') }}</strong>
        <span>{{ $t('account.forgotSentMessage') }}</span>
      </div>

      <form v-else ref="formRef" novalidate class="auth-form" @submit.prevent="submit">
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
        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
        <BaseButton type="submit" variant="primary" :loading="isLoading" :disabled="isLoading" class="auth-submit">
          {{ $t('account.forgotSubmit') }}
        </BaseButton>
      </form>

      <p class="auth-link">
        <router-link to="/login">{{ $t('account.backToLogin') }}</router-link>
      </p>
    </BaseCard>
  </div>
</template>

<style scoped src="../assets/auth.css"></style>
