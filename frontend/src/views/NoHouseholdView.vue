<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { translateApiError } from '../utils/apiErrors'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import { Home, Users } from 'lucide-vue-next'

const router = useRouter()
const authStore = useAuthStore()
const repo = createOnlineHouseholdsRepository()
const { showToast } = useToast()
const { t } = useI18n()

// Haushalt gründen
const newHouseholdName = ref('')
const createLoading = ref(false)

async function createHousehold() {
  if (!newHouseholdName.value.trim()) return
  createLoading.value = true
  try {
    const result = await repo.create(newHouseholdName.value.trim())
    await authStore.fetchMe()
    authStore.switchHousehold(result.id)
    router.push('/shopping')
  } catch (err: any) {
    showToast(translateApiError(err), 'error')
  } finally {
    createLoading.value = false
  }
}

// Mit Code beitreten
const joinCode = ref('')
const joinLoading = ref(false)

async function joinHousehold() {
  if (!joinCode.value.trim()) return
  joinLoading.value = true
  try {
    const result = await repo.join(joinCode.value.trim().toUpperCase())
    showToast(t('household.joinSuccess', { name: result.name }), 'success')
    await authStore.fetchMe()
    authStore.switchHousehold(result.id)
    router.push('/shopping')
  } catch (err: any) {
    showToast(translateApiError(err), 'error')
  } finally {
    joinLoading.value = false
  }
}
</script>

<template>
  <div class="no-household-page">
    <h1 class="no-household-title"><Home :size="24" /> {{ $t('noHousehold.title') }}</h1>
    <p class="no-household-subtitle">{{ $t('noHousehold.subtitle') }}</p>

    <div class="no-household-cards">
      <!-- Karte: Haushalt gründen -->
      <BaseCard>
        <h2 class="card-title"><Home :size="18" /> {{ $t('noHousehold.createTitle') }}</h2>
        <p class="card-hint">{{ $t('noHousehold.createHint') }}</p>
        <form @submit.prevent="createHousehold" class="card-form">
          <BaseInput
            v-model="newHouseholdName"
            :label="$t('auth.householdName')"
            :placeholder="$t('auth.householdPlaceholder')"
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
        <h2 class="card-title"><Users :size="18" /> {{ $t('noHousehold.joinTitle') }}</h2>
        <p class="card-hint">{{ $t('noHousehold.joinHint') }}</p>
        <form @submit.prevent="joinHousehold" class="card-form">
          <BaseInput
            v-model="joinCode"
            :label="$t('auth.inviteCodeLabel')"
            :placeholder="$t('auth.inviteCodePlaceholder')"
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
      <BaseButton variant="ghost" @click="authStore.logout()">
        {{ $t('auth.logout') }}
      </BaseButton>
    </div>
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
  font-size: var(--text-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text);
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
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
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
