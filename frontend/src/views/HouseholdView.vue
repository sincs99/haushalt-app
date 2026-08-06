<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { useToast } from '../composables/useToast'
import type { HouseholdMemberInfo } from '../types'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseSpinner from '../components/ui/BaseSpinner.vue'

const router = useRouter()
const authStore = useAuthStore()
const repo = createOnlineHouseholdsRepository()
const { showToast } = useToast()

// Invite-Code
const inviteCode = ref('')
const inviteCodeLoading = ref(false)

// Join
const joinCode = ref('')
const joinLoading = ref(false)

// Members
const members = ref<HouseholdMemberInfo[]>([])

async function loadInviteCode() {
  if (!authStore.currentHouseholdId) return
  inviteCodeLoading.value = true
  try {
    inviteCode.value = await repo.fetchInviteCode(authStore.currentHouseholdId)
  } catch {
    showToast('Invite-Code konnte nicht geladen werden', 'error')
  } finally {
    inviteCodeLoading.value = false
  }
}

async function loadMembers() {
  if (!authStore.currentHouseholdId) return
  try {
    members.value = await repo.fetchMembers(authStore.currentHouseholdId)
  } catch {
    // Silent fail
  }
}

async function copyInviteCode() {
  try {
    await navigator.clipboard.writeText(inviteCode.value)
    showToast('Invite-Code kopiert!', 'success')
  } catch {
    showToast('Kopieren fehlgeschlagen', 'error')
  }
}

async function joinHousehold() {
  if (!joinCode.value.trim()) return
  joinLoading.value = true
  try {
    const result = await repo.join(joinCode.value.trim().toUpperCase())
    showToast(`Haushalt "${result.name}" beigetreten!`, 'success')
    await authStore.fetchMe()
    authStore.switchHousehold(result.id)
    joinCode.value = ''
    router.push('/shopping')
  } catch (error: any) {
    const status = error?.response?.status
    if (status === 404) {
      showToast('Code nicht gefunden', 'error')
    } else if (status === 409) {
      showToast('Du bist bereits Mitglied', 'error')
    } else {
      showToast('Beitritt fehlgeschlagen', 'error')
    }
  } finally {
    joinLoading.value = false
  }
}

onMounted(() => {
  loadInviteCode()
  loadMembers()
})

// Bei Household-Wechsel neu laden
watch(() => authStore.currentHouseholdId, () => {
  loadInviteCode()
  loadMembers()
})
</script>

<template>
  <div class="view-page">
    <h1 class="view-title">🏠 Haushalt</h1>

    <!-- Invite-Code Card (prominent) -->
    <BaseCard>
      <h2 class="section-title">Einladungscode</h2>
      <p class="section-hint">Teile diesen Code, damit andere deinem Haushalt beitreten können:</p>
      <div v-if="inviteCodeLoading" class="loading-center">
        <BaseSpinner size="sm" />
      </div>
      <div v-else class="invite-code-display">
        <code class="invite-code">{{ inviteCode || '...' }}</code>
        <BaseButton
          variant="secondary"
          size="sm"
          @click="copyInviteCode"
          :disabled="!inviteCode"
        >
          📋 Kopieren
        </BaseButton>
      </div>
    </BaseCard>

    <!-- Mitglieder -->
    <BaseCard>
      <h2 class="section-title">Mitglieder</h2>
      <div v-if="members.length > 0" class="member-chips">
        <span v-for="member in members" :key="member.id" class="member-chip">
          <span class="member-chip__avatar">{{ member.display_name.charAt(0).toUpperCase() }}</span>
          <span class="member-chip__name">{{ member.display_name }}</span>
        </span>
      </div>
      <p v-else class="section-hint">Keine Mitglieder geladen.</p>
    </BaseCard>

    <!-- Haushalt beitreten -->
    <BaseCard>
      <h2 class="section-title">Anderem Haushalt beitreten</h2>
      <form @submit.prevent="joinHousehold" class="join-form">
        <input
          v-model="joinCode"
          type="text"
          placeholder="Einladungscode eingeben"
          class="join-form__input"
          :disabled="joinLoading"
        />
        <BaseButton
          type="submit"
          variant="primary"
          size="sm"
          :loading="joinLoading"
          :disabled="joinLoading || !joinCode.trim()"
        >
          Beitreten
        </BaseButton>
      </form>
    </BaseCard>

    <!-- Logout-Button für Mobile (auf Desktop in Top-Bar) -->
    <div class="mobile-logout">
      <BaseButton variant="ghost" @click="authStore.logout()" class="mobile-logout__btn">
        Abmelden
      </BaseButton>
    </div>
  </div>
</template>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.view-title {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: var(--font-weight-bold);
  color: var(--color-text);
}

.section-title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.section-hint {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  margin: 0 0 var(--space-3);
}

/* Loading */
.loading-center {
  display: flex;
  justify-content: center;
  padding: var(--space-4) 0;
}

/* Invite-Code gross + prominent */
.invite-code-display {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.invite-code {
  flex: 1;
  padding: var(--space-3) var(--space-4);
  background: var(--color-neutral-50);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-md);
  font-size: var(--text-lg);
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  letter-spacing: 2px;
  font-weight: var(--font-weight-bold);
  color: var(--color-text);
  word-break: break-all;
  text-align: center;
}

/* Mitglieder-Chips */
.member-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.member-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-3);
  background: var(--color-neutral-100);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
}

.member-chip__avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-bold);
}

.member-chip__name {
  color: var(--color-text);
  font-weight: var(--font-weight-medium);
}

/* Join-Form */
.join-form {
  display: flex;
  gap: var(--space-2);
}

.join-form__input {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--color-surface);
  color: var(--color-text);
  text-transform: uppercase;
}

.join-form__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* Mobile Logout */
.mobile-logout {
  display: flex;
  justify-content: center;
  padding: var(--space-4) 0;
}

@media (min-width: 768px) {
  .mobile-logout { display: none; }
}
</style>
