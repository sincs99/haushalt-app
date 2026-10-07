<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { createOnlineHouseholdsRepository, type InviteCodeInfo } from '../repositories/householdsRepository'
import { createOnlineExpensesRepository } from '../repositories/expensesRepository'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { useSocket } from '../composables/useSocket'
import { useI18n } from 'vue-i18n'
import { formatRappen } from '../utils/money'
import type { HouseholdMemberInfo } from '../types'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSpinner from '../components/ui/BaseSpinner.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import { PhUserMinus, PhSignOut, PhPlus, PhShareNetwork, PhQrCode } from '@phosphor-icons/vue'
import PageHeader from '../components/ui/PageHeader.vue'
import PushSettings from '../components/PushSettings.vue'
import AiSettingsCard from '../components/AiSettingsCard.vue'
import WidgetSettingsCard from '../components/WidgetSettingsCard.vue'

const router = useRouter()
const authStore = useAuthStore()
const repo = createOnlineHouseholdsRepository()
const expensesRepo = createOnlineExpensesRepository()
const { notifySuccess, notifyError } = useToast()
const { run, isPending } = useAsyncAction()
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
  const householdId = authStore.currentHouseholdId
  const name = householdName.value.trim()
  if (!householdId || !nameChanged.value || !name) return
  renameSaving.value = true
  await run(() => repo.rename(householdId, name), {
    key: 'rename',
    success: t('household.renameSuccess'),
    error: t('household.renameError'),
  })
  renameSaving.value = false
}

// ── Mitglieder ──
const members = ref<HouseholdMemberInfo[]>([])

async function fetchMembers() {
  if (!authStore.currentHouseholdId) return
  members.value = await repo.fetchMembers(authStore.currentHouseholdId)
}

// Erstes Laden mit Lade-/Fehlerzustand (statt „Keine Mitglieder geladen.“)
const { loadError: membersLoadError, reloading: membersLoading, reload: reloadMembers } = useLoader(fetchMembers)

/** Nachladen nach Socket-Events/Entfernen: Fehler still, die Liste bleibt stehen */
async function loadMembers() {
  try {
    await fetchMembers()
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
  const householdId = authStore.currentHouseholdId
  const member = memberToRemove.value
  if (!householdId || !member) return
  removeMemberLoading.value = true
  const ok = await run(() => repo.removeMember(householdId, member.id), {
    key: 'removeMember',
    error: t('household.removeMemberError'),
  })
  if (ok) {
    removeMemberDialogOpen.value = false
    memberToRemove.value = null
    await loadMembers()
    // Backend erneuert beim Entfernen den Einladungscode
    loadInviteCode()
  }
  removeMemberLoading.value = false
}

// ── Haushalt verlassen ──
const leaveDialogOpen = ref(false)
const leaveLoading = ref(false)
/** Offener Saldo beim Verlassen: Betrag + Richtung (positiv = dir steht etwas zu) */
const leaveBalance = ref<{ amount: string; owed: boolean } | null>(null)
const leaveChecking = ref(false)

async function openLeaveDialog() {
  if (!authStore.currentHouseholdId || !authStore.user || leaveChecking.value) return
  leaveBalance.value = null
  leaveChecking.value = true

  try {
    const balances = await expensesRepo.getBalances(authStore.currentHouseholdId)
    const myBalance = balances.balances.find(b => b.user_id === authStore.user!.id)
    if (myBalance && myBalance.saldo_rappen !== 0) {
      const currency = authStore.currentHousehold?.currency ?? 'CHF'
      leaveBalance.value = {
        amount: formatRappen(Math.abs(myBalance.saldo_rappen), currency),
        owed: myBalance.saldo_rappen > 0,
      }
    }
  } catch {
    // Balances nicht ladbar — Dialog trotzdem zeigen
  } finally {
    leaveChecking.value = false
  }

  leaveDialogOpen.value = true
}

async function confirmLeave() {
  const householdId = authStore.currentHouseholdId
  if (!householdId) return
  leaveLoading.value = true
  let target = null as string | null
  // Store markiert den eigenen Austritt: das Socket-Event meldet dann kein „Du wurdest entfernt“
  const ok = await run(
    async () => { target = await authStore.leaveHousehold(householdId, () => repo.leave(householdId)) },
    { key: 'leave', success: t('household.leaveSuccess'), error: t('household.leaveError') },
  )
  leaveLoading.value = false
  if (ok && target) {
    leaveDialogOpen.value = false
    // Dialog nimmt erst seinen History-Eintrag zurück, dann navigieren
    await nextTick()
    router.replace(target)
  }
}

// ── Einladen ──
const inviteCode = ref('')
const inviteExpiresAt = ref<string | null>(null)
const inviteExpired = ref(false)

const inviteExpiryLabel = computed(() => {
  if (!inviteExpiresAt.value) return ''
  return new Date(inviteExpiresAt.value).toLocaleString(
    locale.value === 'de' ? 'de-CH' : 'en-US',
    { dateStyle: 'medium', timeStyle: 'short' },
  )
})

function applyInviteInfo(info: InviteCodeInfo) {
  inviteCode.value = info.inviteCode
  inviteExpiresAt.value = info.expiresAt
  inviteExpired.value = info.expired
}
const inviteCodeLoading = ref(false)

async function loadInviteCode() {
  if (!authStore.currentHouseholdId) return
  inviteCodeLoading.value = true
  try {
    applyInviteInfo(await repo.fetchInviteCode(authStore.currentHouseholdId))
  } catch (error: unknown) {
    notifyError(t('household.inviteLoadError'), error)
  } finally {
    inviteCodeLoading.value = false
  }
}

const rotateDialogOpen = ref(false)
const rotateLoading = computed(() => isPending('rotate'))

async function confirmRotateInviteCode() {
  const householdId = authStore.currentHouseholdId
  if (!householdId) return
  const ok = await run(async () => applyInviteInfo(await repo.rotateInviteCode(householdId)), {
    key: 'rotate',
    success: t('household.rotateCodeSuccess'),
  })
  if (ok) rotateDialogOpen.value = false
}

async function copyInviteCode() {
  try {
    await navigator.clipboard.writeText(inviteCode.value)
    notifySuccess(t('household.codeCopied'))
  } catch {
    notifyError(t('household.copyFailed'))
  }
}

async function shareInvite() {
  const householdName = authStore.currentHousehold?.name ?? ''
  // Link auf die Registrierung mit vorausgefülltem Code (RegisterView liest ?code)
  const link = `${window.location.origin}/register?code=${encodeURIComponent(inviteCode.value)}`
  const shareText = t('household.shareText', { name: householdName, code: inviteCode.value, link })

  if (navigator.share) {
    try {
      await navigator.share({
        title: t('household.shareTitle'),
        text: shareText,
      })
    } catch (err: unknown) {
      // User hat Share-Dialog abgebrochen — kein Fehler
      if (err instanceof DOMException && err.name !== 'AbortError') {
        // Fallback bei anderem Fehler
        await copyShareText(shareText)
      }
    }
  } else {
    // Desktop-Fallback: in Clipboard kopieren
    await copyShareText(shareText)
  }
}

async function copyShareText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    notifySuccess(t('household.shareCopied'))
  } catch {
    notifyError(t('household.copyFailed'))
  }
}

// ── Neuen Haushalt erstellen (Dialog) ──
const createDialogOpen = ref(false)
const newHouseholdName = ref('')
const createNewLoading = ref(false)

async function createNewHousehold() {
  const name = newHouseholdName.value.trim()
  if (!name) return
  createNewLoading.value = true
  const ok = await run(async () => {
    const result = await repo.create(name)
    await authStore.fetchMe()
    authStore.switchHousehold(result.id)
    return result
  }, {
    key: 'create',
    success: (result) => t('household.createNewSuccess', { name: result.name }),
    error: t('household.createError'),
  })
  createNewLoading.value = false
  if (ok) {
    createDialogOpen.value = false
    newHouseholdName.value = ''
    await nextTick()
    router.push('/dashboard')
  }
}

// ── Join ──
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
  if (ok) {
    joinCode.value = ''
    router.push('/dashboard')
  }
}

// ── Abmelden: offline nachfragen (ohne Netz ist eine erneute Anmeldung nicht möglich) ──
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
  members.value = []
  reloadMembers()
}

onMounted(() => {
  initData()
  on('household_member_joined', onMemberJoined)
  on('household_member_left', onMemberLeft)
  on('household_member_removed', onMemberRemoved)
  on('household_updated', onHouseholdUpdated)
})

onUnmounted(() => {
  off('household_member_joined', onMemberJoined)
  off('household_member_left', onMemberLeft)
  off('household_member_removed', onMemberRemoved)
  off('household_updated', onHouseholdUpdated)
})

watch(() => authStore.currentHouseholdId, (id) => {
  // Nach Verlassen des letzten Haushalts nichts mehr laden
  if (id) initData()
})
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('household.title')" />

    <!-- ══ Sektion: Haushalt ══ -->
    <BaseCard>
      <h2 class="section-title">{{ $t('household.title') }}</h2>

      <!-- Admin: Editierbarer Name -->
      <form v-if="isAdmin" class="rename-row" @submit.prevent="saveHouseholdName">
        <BaseInput
          v-model="householdName"
          :label="$t('household.nameLabel')"
          :placeholder="$t('household.nameLabel')"
          maxlength="100"
        />
        <BaseButton
          type="submit"
          variant="primary"
          size="sm"
          :disabled="!nameChanged || !householdName.trim() || renameSaving"
          :loading="renameSaving"
        >
          {{ $t('household.saveName') }}
        </BaseButton>
      </form>

      <!-- Member: Nur Name anzeigen -->
      <div v-else class="household-name-display">
        <span class="household-name-label">{{ $t('household.nameLabel') }}</span>
        <span class="household-name-value">{{ authStore.currentHousehold?.name }}</span>
      </div>

      <!-- Haushalt verlassen -->
      <div class="leave-section">
        <BaseButton variant="danger" size="sm" :loading="leaveChecking" @click="openLeaveDialog">
          <PhSignOut :size="16" />
          {{ $t('household.leaveTitle') }}
        </BaseButton>
      </div>
    </BaseCard>

    <!-- ══ Sektion: Mitglieder ══ -->
    <BaseCard>
      <h2 class="section-title">{{ $t('household.members') }}</h2>
      <div v-if="membersLoading && members.length === 0" class="member-list">
        <BaseSkeleton v-for="i in 2" :key="i" width="100%" height="48px" />
      </div>
      <BaseErrorState
        v-else-if="membersLoadError && members.length === 0"
        :retrying="membersLoading"
        @retry="reloadMembers"
      />
      <div v-else-if="members.length > 0" class="member-list">
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
            <PhUserMinus :size="20" />
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
      <div v-else>
        <div class="invite-code-display">
          <code class="invite-code">{{ inviteCode || '...' }}</code>
        </div>
        <p v-if="inviteExpired" class="section-hint invite-expired" role="alert">
          {{ $t('household.inviteExpired') }}
          <button
            v-if="isAdmin"
            type="button"
            class="invite-expired-link"
            :disabled="rotateLoading"
            @click="rotateDialogOpen = true"
          >
            {{ $t('household.inviteExpiredAction') }}
          </button>
          <template v-else>{{ $t('household.inviteExpiredAskAdmin') }}</template>
        </p>
        <p v-else-if="inviteExpiryLabel" class="section-hint">
          {{ $t('household.inviteValidUntil', { date: inviteExpiryLabel }) }}
        </p>
        <div class="invite-actions">
          <BaseButton
            variant="primary"
            size="sm"
            @click="shareInvite"
            :disabled="!inviteCode"
          >
            <PhShareNetwork :size="16" />
            {{ $t('household.shareInvite') }}
          </BaseButton>
          <BaseButton
            variant="secondary"
            size="sm"
            @click="copyInviteCode"
            :disabled="!inviteCode"
          >
            {{ $t('household.copyCode') }}
          </BaseButton>
          <BaseButton
            v-if="isAdmin"
            variant="ghost"
            size="sm"
            :disabled="!inviteCode"
            @click="rotateDialogOpen = true"
          >
            {{ $t('household.rotateCode') }}
          </BaseButton>
        </div>
        <p v-if="isAdmin" class="section-hint">{{ $t('household.rotateCodeHint') }}</p>
      </div>

      <!-- Beitreten -->
      <div class="join-section">
        <h3 class="subsection-title">{{ $t('household.joinTitle') }}</h3>
        <form @submit.prevent="joinHousehold" class="join-form">
          <input
            v-model="joinCode"
            type="text"
            :placeholder="$t('household.joinPlaceholder')"
            :aria-label="$t('auth.inviteCodeLabel')"
            class="join-form__input"
            autocapitalize="characters"
            autocomplete="off"
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
          <PhPlus :size="16" />
          {{ $t('household.createNewTitle') }}
        </BaseButton>
      </div>
    </BaseCard>

    <!-- ══ Sektion: Tags (NFC/QR) ══ -->
    <BaseCard>
      <h2 class="section-title">{{ $t('tags.title') }}</h2>
      <p class="section-hint">{{ $t('tags.householdHint') }}</p>
      <BaseButton variant="secondary" size="sm" @click="router.push('/tags')">
        <PhQrCode :size="16" />
        {{ $t('tags.manage') }}
      </BaseButton>
    </BaseCard>

    <!-- ══ Sektion: Homescreen-Widget (Scriptable) ══ -->
    <WidgetSettingsCard />

    <!-- ══ Sektion: KI-Assistent (nur wenn auf dem Server eingerichtet) ══ -->
    <AiSettingsCard />

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

      <PushSettings />

      <!-- Logout-Button für Mobile -->
      <div class="mobile-logout">
        <BaseButton variant="ghost" @click="requestLogout" class="mobile-logout__btn">
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
      <p v-if="leaveBalance" class="dialog-warning-text">
        {{ $t(leaveBalance.owed ? 'household.leaveBalanceOwed' : 'household.leaveBalanceOwe', { amount: leaveBalance.amount }) }}
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

    <!-- ══ Dialog: Einladungscode erneuern ══ -->
    <BaseDialog
      :open="rotateDialogOpen"
      :title="$t('household.rotateCode')"
      danger
      @close="rotateDialogOpen = false"
    >
      <p>{{ $t('household.rotateCodeConfirm') }}</p>

      <template #footer>
        <BaseButton variant="ghost" size="sm" @click="rotateDialogOpen = false">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton
          variant="danger"
          size="sm"
          :loading="rotateLoading"
          @click="confirmRotateInviteCode"
        >
          {{ $t('household.rotateCode') }}
        </BaseButton>
      </template>
    </BaseDialog>

    <!-- ══ Dialog: Offline abmelden ══ -->
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

    <!-- ══ Dialog: Neuen Haushalt erstellen ══ -->
    <BaseDialog
      :open="createDialogOpen"
      :title="$t('household.createNewTitle')"
      @close="createDialogOpen = false"
    >
      <form id="create-household-form" @submit.prevent="createNewHousehold" class="create-new-form">
        <BaseInput
          v-model="newHouseholdName"
          :label="$t('auth.householdName')"
          :placeholder="$t('auth.householdPlaceholder')"
          maxlength="100"
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
          type="submit"
          form="create-household-form"
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

.section-title {
  margin: 0 0 var(--space-3);
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
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
  border-top: 1px solid var(--line);
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
  background: var(--color-surface-subtle);
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
  padding: var(--badge-padding);
  background: var(--color-primary-light);
  color: var(--color-primary-strong);
  font-size: var(--text-badge);
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
  background: var(--chip);
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
  margin-bottom: var(--space-3);
}

.invite-expired {
  color: var(--color-danger);
}

.invite-expired-link {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font: inherit;
  font-weight: var(--font-weight-bold);
  text-decoration: underline;
  cursor: pointer;
}

.invite-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.invite-code {
  flex: 1;
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-subtle);
  border: 1px solid var(--line);
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
  border: 1px solid var(--line-strong);
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
  border-top: 1px solid var(--line);
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
  border: 1px solid var(--line);
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
  border-top: 1px solid var(--line);
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
