<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useI18n } from 'vue-i18n'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import { PhHouse, PhUsers } from '@phosphor-icons/vue'

const router = useRouter()
const authStore = useAuthStore()
const repo = createOnlineHouseholdsRepository()
const { run } = useAsyncAction()
const { t } = useI18n()

// Sobald Haushalte via Socket/fetchMe erscheinen → weiterleiten
watch(() => authStore.households.length, (len) => {
  if (len > 0 && router.currentRoute.value.path === '/no-household') {
    router.replace('/dashboard')
  }
})

// Haushalt gründen
const newHouseholdName = ref('')
const createLoading = ref(false)

async function createHousehold() {
  const name = newHouseholdName.value.trim()
  if (!name) return
  createLoading.value = true
  const ok = await run(async () => {
    const result = await repo.create(name)
    await authStore.fetchMe()
    authStore.switchHousehold(result.id)
  }, { key: 'create', error: t('household.createError') })
  createLoading.value = false
  if (ok) router.push('/dashboard')
}

// Mit Code beitreten
const joinCode = ref('')
const joinLoading = ref(false)

async function joinHousehold() {
  const code = joinCode.value.trim().toUpperCase()
  if (!code) return
  joinLoading.value = true
  const ok = await run(async () => {
    const result = await repo.join(code)
    await authStore.fetchMe()
    authStore.switchHousehold(result.id)
    return result
  }, {
    key: 'join',
    success: (result) => t('household.joinSuccess', { name: result.name }),
    error: t('household.joinFailed'),
  })
  joinLoading.value = false
  if (ok) router.push('/dashboard')
}

// Abmelden: offline nachfragen (ohne Netz ist eine erneute Anmeldung nicht möglich)
const logoutDialogOpen = ref(false)

function requestLogout() {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    logoutDialogOpen.value = true
    return
  }
  authStore.logout({ reason: 'user' })
}

function confirmLogout() {
  logoutDialogOpen.value = false
  authStore.logout({ reason: 'user' })
}
</script>

<template>
  <div class="no-household-page">
    <h1 class="no-household-title"><PhHouse :size="24" /> {{ $t('noHousehold.title') }}</h1>
    <p class="no-household-subtitle">{{ $t('noHousehold.subtitle') }}</p>

    <div class="no-household-cards">
      <!-- Karte: Haushalt gründen -->
      <BaseCard>
        <h2 class="card-title"><PhHouse :size="18" /> {{ $t('noHousehold.createTitle') }}</h2>
        <p class="card-hint">{{ $t('noHousehold.createHint') }}</p>
        <form @submit.prevent="createHousehold" class="card-form">
          <BaseInput
            v-model="newHouseholdName"
            :label="$t('auth.householdName')"
            :placeholder="$t('auth.householdPlaceholder')"
            maxlength="100"
          />
          <BaseButton
            type="submit"
            variant="primary"
            :loading="createLoading"
            :disabled="createLoading || !newHouseholdName.trim()"
          >
            {{ $t('noHousehold.createButton') }}
          </BaseButton>
        </form>
      </BaseCard>

      <!-- Karte: Mit Code beitreten -->
      <BaseCard>
        <h2 class="card-title"><PhUsers :size="18" /> {{ $t('noHousehold.joinTitle') }}</h2>
        <p class="card-hint">{{ $t('noHousehold.joinHint') }}</p>
        <form @submit.prevent="joinHousehold" class="card-form">
          <BaseInput
            v-model="joinCode"
            :label="$t('auth.inviteCodeLabel')"
            :placeholder="$t('auth.inviteCodePlaceholder')"
            autocapitalize="characters"
            autocomplete="off"
            style="text-transform: uppercase"
          />
          <BaseButton
            type="submit"
            variant="primary"
            :loading="joinLoading"
            :disabled="joinLoading || !joinCode.trim()"
          >
            {{ $t('household.joinButton') }}
          </BaseButton>
        </form>
      </BaseCard>
    </div>

    <div class="no-household-logout">
      <BaseButton variant="ghost" @click="requestLogout">
        {{ $t('auth.logout') }}
      </BaseButton>
    </div>

    <BaseDialog
      :open="logoutDialogOpen"
      :title="$t('auth.logoutOfflineTitle')"
      danger
      @close="logoutDialogOpen = false"
    >
      <p>{{ $t('auth.logoutOfflineConfirm') }}</p>
      <template #footer>
        <BaseButton variant="ghost" size="sm" @click="logoutDialogOpen = false">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton variant="danger" size="sm" @click="confirmLogout">
          {{ $t('auth.logout') }}
        </BaseButton>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.no-household-page {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  background: var(--color-bg);
}

.no-household-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-1);
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.no-household-subtitle {
  margin: 0 0 var(--space-6);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  text-align: center;
}

.no-household-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  width: 100%;
  max-width: 400px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.card-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.card-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.no-household-logout {
  margin-top: var(--space-6);
}
</style>
