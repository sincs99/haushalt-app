<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PhHouse } from '@phosphor-icons/vue'
import { PASSWORD_MIN_LENGTH } from '../stores/auth'
import { accountRepository } from '../repositories/accountRepository'
import { errorText } from '../composables/useToast'

const route = useRoute()
const { t } = useI18n()

const token = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))
const password = ref('')
const passwordRepeat = ref('')
const error = ref('')
const done = ref(false)
const isLoading = ref(false)
const submitted = ref(false)
const formRef = ref<HTMLFormElement | null>(null)

const passwordError = computed(() => {
  if (!submitted.value) return undefined
  if (!password.value) return t('auth.passwordRequired')
  if (password.value.length < PASSWORD_MIN_LENGTH) return t('auth.passwordTooShort')
  return undefined
})
const repeatError = computed(() =>
  submitted.value && passwordRepeat.value !== password.value ? t('account.passwordMismatch') : undefined,
)

onMounted(() => formRef.value?.querySelector('input')?.focus())

async function submit() {
  error.value = ''
  submitted.value = true
  if (passwordError.value || repeatError.value) return
  isLoading.value = true
  try {
    await accountRepository.resetPassword(token.value, password.value)
    done.value = true
  } catch (err) {
    error.value = errorText(t('account.resetFailed'), err)
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <BaseCard padding="lg" class="auth-card">
      <h1 class="auth-title"><PhHouse :size="24" /> {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('account.resetSubtitle') }}</p>

      <div v-if="!token" class="auth-info" role="alert">
        <strong>{{ $t('account.linkInvalidTitle') }}</strong>
        <span>{{ $t('account.linkInvalidMessage') }}</span>
      </div>

      <div v-else-if="done" class="auth-info" role="status">
        <strong>{{ $t('account.resetDoneTitle') }}</strong>
        <span>{{ $t('account.resetDoneMessage') }}</span>
      </div>

      <form v-else ref="formRef" novalidate class="auth-form" @submit.prevent="submit">
        <BaseInput
          v-model="password"
          :label="$t('account.newPassword')"
          type="password"
          autocomplete="new-password"
          :error="passwordError"
        />
        <BaseInput
          v-model="passwordRepeat"
          :label="$t('account.repeatPassword')"
          type="password"
          autocomplete="new-password"
          :error="repeatError"
        />
        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
        <BaseButton type="submit" variant="primary" :loading="isLoading" :disabled="isLoading" class="auth-submit">
          {{ $t('account.resetSubmit') }}
        </BaseButton>
      </form>

      <p class="auth-link">
        <router-link v-if="done || !token" to="/login">{{ $t('auth.loginHere') }}</router-link>
        <router-link v-else to="/forgot-password">{{ $t('account.requestNewLink') }}</router-link>
      </p>
    </BaseCard>
  </div>
</template>

<style scoped src="../assets/auth.css"></style>
