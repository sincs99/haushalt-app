<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhKey, PhTrash } from '@phosphor-icons/vue'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseDialog from './ui/BaseDialog.vue'
import BaseInput from './ui/BaseInput.vue'
import { PASSWORD_MIN_LENGTH, useAuthStore } from '../stores/auth'
import { accountRepository } from '../repositories/accountRepository'
import { errorText, useToast } from '../composables/useToast'

/**
 * Konto: Passwort ändern und Konto löschen. Beides verlangt das aktuelle Passwort.
 * Konto löschen ist Pflicht für die App Stores (Apple 5.1.1(v)) und DSGVO Art. 17.
 */
const authStore = useAuthStore()
const { t } = useI18n()
const { notifySuccess } = useToast()

// ── Passwort ändern ──
const passwordDialogOpen = ref(false)
const currentPassword = ref('')
const newPassword = ref('')
const newPasswordRepeat = ref('')
const passwordSubmitted = ref(false)
const passwordLoading = ref(false)
const passwordError = ref('')

const newPasswordError = computed(() => {
  if (!passwordSubmitted.value) return undefined
  if (!newPassword.value) return t('auth.passwordRequired')
  if (newPassword.value.length < PASSWORD_MIN_LENGTH) return t('auth.passwordTooShort')
  return undefined
})
const repeatError = computed(() =>
  passwordSubmitted.value && newPasswordRepeat.value !== newPassword.value ? t('account.passwordMismatch') : undefined,
)
const currentPasswordError = computed(() =>
  passwordSubmitted.value && !currentPassword.value ? t('auth.passwordRequired') : undefined,
)

function openPasswordDialog() {
  currentPassword.value = ''
  newPassword.value = ''
  newPasswordRepeat.value = ''
  passwordSubmitted.value = false
  passwordError.value = ''
  passwordDialogOpen.value = true
}

async function submitPassword() {
  passwordSubmitted.value = true
  passwordError.value = ''
  if (currentPasswordError.value || newPasswordError.value || repeatError.value) return
  passwordLoading.value = true
  try {
    const tokens = await accountRepository.changePassword(currentPassword.value, newPassword.value)
    authStore.applyTokenResponse(tokens)
    passwordDialogOpen.value = false
    notifySuccess(t('account.passwordChanged'))
  } catch (err) {
    passwordError.value = errorText(t('account.passwordChangeFailed'), err)
  } finally {
    passwordLoading.value = false
  }
}

// ── Konto löschen ──
const deleteDialogOpen = ref(false)
const deletePassword = ref('')
const deleteSubmitted = ref(false)
const deleteLoading = ref(false)
const deleteError = ref('')
const deletePasswordError = computed(() =>
  deleteSubmitted.value && !deletePassword.value ? t('auth.passwordRequired') : undefined,
)

function openDeleteDialog() {
  deletePassword.value = ''
  deleteSubmitted.value = false
  deleteError.value = ''
  deleteDialogOpen.value = true
}

async function submitDelete() {
  deleteSubmitted.value = true
  deleteError.value = ''
  if (deletePasswordError.value) return
  deleteLoading.value = true
  try {
    await accountRepository.deleteAccount(deletePassword.value)
    deleteDialogOpen.value = false
    notifySuccess(t('account.deleted'))
    // Backend hat alle Sitzungen widerrufen; lokalen Zustand verwerfen und zur Anmeldung
    await authStore.logout({ reason: 'user' })
  } catch (err) {
    deleteError.value = errorText(t('account.deleteFailed'), err)
  } finally {
    deleteLoading.value = false
  }
}
</script>

<template>
  <BaseCard>
    <h2 class="section-title">{{ t('account.title') }}</h2>
    <p class="section-hint">{{ t('account.signedInAs', { email: authStore.user?.email ?? '' }) }}</p>
    <div class="account-settings__actions">
      <BaseButton variant="secondary" size="sm" @click="openPasswordDialog">
        <PhKey :size="16" /> {{ t('account.changePassword') }}
      </BaseButton>
      <BaseButton variant="ghost" size="sm" class="account-settings__danger" @click="openDeleteDialog">
        <PhTrash :size="16" /> {{ t('account.deleteAccount') }}
      </BaseButton>
    </div>

    <!-- ══ Dialog: Passwort ändern ══ -->
    <BaseDialog :open="passwordDialogOpen" :title="t('account.changePassword')" @close="passwordDialogOpen = false">
      <form novalidate class="account-settings__form" @submit.prevent="submitPassword">
        <BaseInput
          v-model="currentPassword"
          :label="t('account.currentPassword')"
          type="password"
          autocomplete="current-password"
          :error="currentPasswordError"
        />
        <BaseInput
          v-model="newPassword"
          :label="t('account.newPassword')"
          type="password"
          autocomplete="new-password"
          :error="newPasswordError"
        />
        <BaseInput
          v-model="newPasswordRepeat"
          :label="t('account.repeatPassword')"
          type="password"
          autocomplete="new-password"
          :error="repeatError"
        />
        <p class="section-hint">{{ t('account.changePasswordHint') }}</p>
        <p v-if="passwordError" class="account-settings__error" role="alert">{{ passwordError }}</p>
        <div class="account-settings__dialog-actions">
          <BaseButton variant="ghost" size="sm" type="button" @click="passwordDialogOpen = false">
            {{ t('common.cancel') }}
          </BaseButton>
          <BaseButton variant="primary" size="sm" type="submit" :loading="passwordLoading" :disabled="passwordLoading">
            {{ t('common.save') }}
          </BaseButton>
        </div>
      </form>
    </BaseDialog>

    <!-- ══ Dialog: Konto löschen ══ -->
    <BaseDialog :open="deleteDialogOpen" :title="t('account.deleteAccount')" danger @close="deleteDialogOpen = false">
      <form novalidate class="account-settings__form" @submit.prevent="submitDelete">
        <p class="dialog-warning-text">{{ t('account.deleteWarning') }}</p>
        <BaseInput
          v-model="deletePassword"
          :label="t('account.confirmWithPassword')"
          type="password"
          autocomplete="current-password"
          :error="deletePasswordError"
        />
        <p v-if="deleteError" class="account-settings__error" role="alert">{{ deleteError }}</p>
        <div class="account-settings__dialog-actions">
          <BaseButton variant="ghost" size="sm" type="button" @click="deleteDialogOpen = false">
            {{ t('common.cancel') }}
          </BaseButton>
          <BaseButton variant="danger" size="sm" type="submit" :loading="deleteLoading" :disabled="deleteLoading">
            {{ t('account.deleteConfirm') }}
          </BaseButton>
        </div>
      </form>
    </BaseDialog>
  </BaseCard>
</template>

<style scoped>
.account-settings__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.account-settings__danger {
  color: var(--color-danger);
}

.account-settings__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.account-settings__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
}

.account-settings__dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
