<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { createOnlineExpensesRepository } from '../repositories/expensesRepository'
import { useToast } from '../composables/useToast'
import { useSocket } from '../composables/useSocket'
import { useI18n } from 'vue-i18n'
import { translateApiError } from '../utils/apiErrors'
import { formatRappen } from '../utils/money'
import type { HouseholdMemberInfo } from '../types'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSpinner from '../components/ui/BaseSpinner.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import { UserMinus, LogOut, Plus } from 'lucide-vue-next'

const router = useRouter()
const authStore = useAuthStore()
const repo = createOnlineHouseholdsRepository()
const expensesRepo = createOnlineExpensesRepository()
const { showToast } = useToast()
const { t, locale } = useI18n()
const { on, off } = useSocket()

// ── Locale ──
const currentLocale = ref(locale.value)

function changeLocale(newLocale: string) {
  locale.value = newLocale
  localStorage.setItem('haushalt_locale', newLocale)
  currentLocale.value = newLocale
}

// ── Haushalt-Name (Admin: editierbar) ──
const householdName = ref('')
const renameSaving = ref(false)

const isAdmin = computed(() => {
  return authStore.currentHousehold?.role === 'admin'
})

const nameChanged = computed(() => {
  return householdName.value.trim() !== (authStore.currentHousehold?.name ?? '')
})

async function saveHouseholdName() {
  if (!authStore.currentHouseholdId || !nameChanged.value) return
  renameSaving.value = true
  try {
    await repo.rename(authStore.currentHouseholdId, householdName.value.trim())
    showToast(t('household.renameSuccess'), 'success')
  } catch {
    showToast(t('household.renameError'), 'error')
  } finally {
    renameSaving.value = false
  }
}

// ── Mitglieder ──
const members = ref<HouseholdMemberInfo[]>([])

async function loadMembers() {
  if (!authStore.currentHouseholdId) return
  try {
    members.value = await repo.fetchMembers(authStore.currentHouseholdId)
  } catch {
    // Silent fail
  }
}

// ── Mitglied entfernen (Admin) ──
const removeMemberDialogOpen = ref(false)
const memberToRemove = ref<HouseholdMemberInfo | null>(null)
const removeMemberLoading = ref(false)

function openRemoveMemberDialog(member: HouseholdMemberInfo) {
  memberToRemove.value = member
  removeMemberDialogOpen.value = true
}

async function confirmRemoveMember() {
  if (!authStore.currentHouseholdId || !memberToRemove.value) return
  removeMemberLoading.value = true
  try {
    await repo.removeMember(authStore.currentHouseholdId, memberToRemove.value.id)
    showToast(t('household.removeMemberSuccess', { name: memberToRemove.value.display_name }), 'success')
    removeMemberDialogOpen.value = false
    memberToRemove.value = null
    await loadMembers()
  } catch (error: unknown) {
    showToast(translateApiError(error), 'error')
  } finally {
    removeMemberLoading.value = false
  }
}

// ── Haushalt verlassen ──
const leaveDialogOpen = ref(false)
const leaveLoading = ref(false)
const leaveBalanceAmount = ref<string | null>(null)

async function openLeaveDialog() {
  if (!authStore.currentHouseholdId || !authStore.user) return
  leaveBalanceAmount.value = null

  try {
    const balances = await expensesRepo.getBalances(authStore.currentHouseholdId)
    const myBalance = balances.balances.find(b => b.user_id === authStore.user!.id)
    if (myBalance && myBalance.saldo_rappen !== 0) {
      const currency = authStore.currentHousehold?.currency ?? 'CHF'
      leaveBalanceAmount.value = formatRappen(Math.abs(myBalance.saldo_rappen), currency)
    }
  } catch {
    // Balances nicht ladbar — Dialog trotzdem zeigen
  }

  leaveDialogOpen.value = true
}

async function confirmLeave() {
  if (!authStore.currentHouseholdId) return
  leaveLoading.value = true
  try {
    await repo.leave(authStore.currentHouseholdId)
    showToast(t('household.leaveSuccess'), 'success')
    leaveDialogOpen.value = false
    // authStore _handleRemoval wird über Socket-Event ausgelöst
    // Falls kein Socket: manuell fetchMe
    await authStore.fetchMe()
    if (authStore.households.length > 0) {
      router.push('/shopping')
    }
  } catch (error: unknown) {
    showToast(translateApiError(error), 'error')
  } finally {
    leaveLoading.value = false
  }
}

// ── Einladen ──
const inviteCode = ref('')
const inviteCodeLoading = ref(false)

async function loadInviteCode() {
  if (!authStore.currentHouseholdId) return
  inviteCodeLoading.value = true
  try {
    inviteCode.value = await repo.fetchInviteCode(authStore.currentHouseholdId)
  } catch {
    showToast(t('household.inviteLoadError'), 'error')
  } finally {
    inviteCodeLoading.value = false
  }
}

async function copyInviteCode() {
  try {
    await navigator.clipboard.writeText(inviteCode.value)
    showToast(t('household.codeCopied'), 'success')
  } catch {
    showToast(t('household.copyFailed'), 'error')
  }
}

// ── Neuen Haushalt erstellen (Dialog) ──
const createDialogOpen = ref(false)
const newHouseholdName = ref('')
const createNewLoading = ref(false)

async function createNewHousehold() {
  if (!newHouseholdName.value.trim()) return
  createNewLoading.value = true
  try {
    const result = await repo.create(newHouseholdName.value.trim())
    showToast(t('household.createNewSuccess', { name: result.name }), 'success')
    await authStore.fetchMe()
    authStore.switchHousehold(result.id)
    createDialogOpen.value = false
    newHouseholdName.value = ''
    router.push('/shopping')
  } catch (error: unknown) {
    showToast(translateApiError(error), 'error')
  } finally {
    createNewLoading.value = false
  }
}

// ── Join ──
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
    joinCode.value = ''
    router.push('/shopping')
  } catch (error: unknown) {
    showToast(translateApiError(error), 'error')
  } finally {
    joinLoading.value = false
  }
}

// ── Socket-Events: Members nachladen bei Änderungen ──
function onMemberJoined() {
  loadMembers()
}
function onMemberLeft() {
  loadMembers()
}
function onMemberRemoved() {
  loadMembers()
}
function onHouseholdUpdated(data: { id: string; name: string }) {
  if (data.id === authStore.currentHouseholdId) {
    householdName.value = data.name
  }
}

// ── Init + Watch ──
function initData() {
  householdName.value = authStore.currentHousehold?.name ?? ''
  loadInviteCode()
  loadMembers()
}

onMounted(() => {
  initData()
  on('household_member_joined', onMemberJoined)
  on('household_member_left', onMemberLeft)
  on('household_member_removed', onMemberRemoved)
  on('household_updated', onHouseholdUpdated)
})

import { onUnmounted } from 'vue'
onUnmounted(() => {
  off('household_member_joined', onMemberJoined)
  off('household_member_left', onMemberLeft)
  off('household_member_removed', onMemberRemoved)
  off('household_updated', onHouseholdUpdated)
})

watch(() => authStore.currentHouseholdId, () => {
  initData()
})
</script>

<template>
  <div class="view-page">
    <h1 class="view-title">{{ $t('household.title') }}</h1>

    <!-- ══ Sektion: Haushalt ══ -->
    <BaseCard>
      <h2 class="section-title">{{ $t('household.title') }}</h2>

      <!-- Admin: Editierbarer Name -->
      <div v-if="isAdmin" class="rename-row">
        <BaseInput
          v-model="householdName"
          :label="$t('household.nameLabel')"
          :placeholder="$t('household.nameLabel')"
        />
        <BaseButton
          variant="primary"
          size="sm"
          :disabled="!nameChanged || renameSaving"
          :loading="renameSaving"
          @click="saveHouseholdName"
        >
          {{ $t('household.saveName') }}
        </BaseButton>
      </div>

      <!-- Member: Nur Name anzeigen -->
      <div v-else class="household-name-display">
        <span class="household-name-label">{{ $t('household.nameLabel') }}</span>
        <span class="household-name-value">{{ authStore.currentHousehold?.name }}</span>
      </div>

      <!-- Haushalt verlassen -->
      <div class="leave-section">
        <BaseButton variant="danger" size="sm" @click="openLeaveDialog">
          <LogOut :size="16" />
          {{ $t('household.leaveTitle') }}
        </BaseButton>
      </div>
    </BaseCard>

    <!-- ══ Sektion: Mitglieder ══ -->
    <BaseCard>
      <h2 class="section-title">{{ $t('household.members') }}</h2>
      <div v-if="members.length > 0" class="member-list">
        <div
          v-for="member in members"
          :key="member.id"
          class="member-row"
        >
          <BaseAvatar :name="member.display_name" :user-id="member.id" size="md" />
          <div class="member-info">
            <span class="member-name">{{ member.display_name }}</span>
            <span v-if="member.role === 'admin'" class="admin-badge">
              {{ $t('household.adminBadge') }}
            </span>
          </div>
          <!-- Admin: Entfernen-Button (nicht bei Admins, nicht bei sich selbst) -->
          <button
            v-if="isAdmin && member.role !== 'admin' && member.id !== authStore.user?.id"
            class="member-remove-btn"
            :aria-label="$t('household.removeMemberButton')"
            @click="openRemoveMemberDialog(member)"
          >
            <UserMinus :size="18" />
          </button>
        </div>
      </div>
      <p v-else class="section-hint">{{ $t('household.noMembers') }}</p>
    </BaseCard>

    <!-- ══ Sektion: Einladen ══ -->
    <BaseCard>
      <h2 class="section-title">{{ $t('household.inviteCode') }}</h2>
      <p class="section-hint">{{ $t('household.inviteHint') }}</p>
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
          {{ $t('household.copyCode') }}
        </BaseButton>
      </div>

      <!-- Beitreten -->
      <div class="join-section">
        <h3 class="subsection-title">{{ $t('household.joinTitle') }}</h3>
        <form @submit.prevent="joinHousehold" class="join-form">
          <input
            v-model="joinCode"
            type="text"
            :placeholder="$t('household.joinPlaceholder')"
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
            {{ $t('household.joinButton') }}
          </BaseButton>
        </form>
      </div>

      <!-- Weiteren Haushalt gründen -->
      <div class="create-new-section">
        <BaseButton variant="ghost" size="sm" @click="createDialogOpen = true">
          <Plus :size="16" />
          {{ $t('household.createNewTitle') }}
        </BaseButton>
      </div>
    </BaseCard>

    <!-- ══ Sektion: App ══ -->
    <BaseCard>
      <h2 class="section-title">{{ $t('household.settings') }}</h2>
      <div class="settings-row">
        <label class="settings-label" for="locale-select">{{ $t('household.language') }}</label>
        <select
          id="locale-select"
          :value="currentLocale"
          @change="changeLocale(($event.target as HTMLSelectElement).value)"
          class="settings-select"
        >
          <option value="de">{{ $t('household.languageDe') }}</option>
          <option value="en">{{ $t('household.languageEn') }}</option>
        </select>
      </div>

      <!-- Logout-Button für Mobile -->
      <div class="mobile-logout">
        <BaseButton variant="ghost" @click="authStore.logout()" class="mobile-logout__btn">
          {{ $t('auth.logout') }}
        </BaseButton>
      </div>
    </BaseCard>

    <!-- ══ Dialog: Haushalt verlassen ══ -->
    <BaseDialog
      :open="leaveDialogOpen"
      :title="$t('household.leaveTitle')"
      danger
      @close="leaveDialogOpen = false"
    >
      <p v-if="leaveBalanceAmount" class="dialog-warning-text">
        {{ $t('household.leaveBalanceWarning', { amount: leaveBalanceAmount }) }}
      </p>
      <p v-else>{{ $t('household.leaveConfirm') }}</p>

      <template #footer>
        <BaseButton variant="ghost" size="sm" @click="leaveDialogOpen = false">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton
          variant="danger"
          size="sm"
          :loading="leaveLoading"
          @click="confirmLeave"
        >
          {{ $t('household.leaveButton') }}
        </BaseButton>
      </template>
    </BaseDialog>

    <!-- ══ Dialog: Mitglied entfernen ══ -->
    <BaseDialog
      :open="removeMemberDialogOpen"
      :title="$t('household.removeMemberTitle')"
      danger
      @close="removeMemberDialogOpen = false"
    >
      <p>{{ $t('household.removeMemberConfirm', { name: memberToRemove?.display_name ?? '' }) }}</p>

      <template #footer>
        <BaseButton variant="ghost" size="sm" @click="removeMemberDialogOpen = false">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton
          variant="danger"
          size="sm"
          :loading="removeMemberLoading"
          @click="confirmRemoveMember"
        >
          {{ $t('household.removeMemberButton') }}
        </BaseButton>
      </template>
    </BaseDialog>

    <!-- ══ Dialog: Neuen Haushalt erstellen ══ -->
    <BaseDialog
      :open="createDialogOpen"
      :title="$t('household.createNewTitle')"
      @close="createDialogOpen = false"
    >
      <form @submit.prevent="createNewHousehold" class="create-new-form">
        <BaseInput
          v-model="newHouseholdName"
          :label="$t('auth.householdName')"
          :placeholder="$t('auth.householdPlaceholder')"
        />
      </form>

      <template #footer>
        <BaseButton variant="ghost" size="sm" @click="createDialogOpen = false">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton
          variant="primary"
          size="sm"
          :loading="createNewLoading"
          :disabled="createNewLoading || !newHouseholdName.trim()"
          @click="createNewHousehold"
        >
          {{ $t('household.createNewButton') }}
        </BaseButton>
      </template>
    </BaseDialog>
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
  margin: 0 0 var(--space-3);
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.subsection-title {
  margin: var(--space-4) 0 var(--space-2);
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.section-hint {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  margin: 0 0 var(--space-3);
}

/* ── Haushalt-Name ── */
.rename-row {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
}

.rename-row .base-input {
  flex: 1;
}

.household-name-display {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.household-name-label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
}

.household-name-value {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.leave-section {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-neutral-200);
}

/* ── Mitglieder ── */
.member-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.member-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-neutral-50);
}

.member-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.member-name {
  font-size: var(--text-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-badge {
  display: inline-flex;
  align-items: center;
  padding: var(--space-0-5) var(--space-2);
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-bold);
  border-radius: var(--radius-full);
  white-space: nowrap;
}

.member-remove-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-text-secondary);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.member-remove-btn:hover {
  color: var(--color-danger);
  background: var(--color-neutral-100);
}

/* ── Invite-Code ── */
.loading-center {
  display: flex;
  justify-content: center;
  padding: var(--space-4) 0;
}

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

/* ── Join-Form ── */
.join-section {
  margin-top: var(--space-3);
}

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

/* ── Neuen Haushalt gründen ── */
.create-new-section {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-neutral-200);
}

.create-new-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

/* ── Settings ── */
.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.settings-label {
  font-size: var(--text-base);
  color: var(--color-text);
  font-weight: var(--font-weight-medium);
}

.settings-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  color: var(--color-text);
  background: var(--color-bg);
  cursor: pointer;
}

.settings-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-primary-light);
}

/* ── Mobile Logout ── */
.mobile-logout {
  display: flex;
  justify-content: center;
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-neutral-200);
}

@media (min-width: 768px) {
  .mobile-logout { display: none; }
}

/* ── Dialog-Warntext ── */
.dialog-warning-text {
  color: var(--color-danger);
  font-weight: var(--font-weight-medium);
}
</style>
