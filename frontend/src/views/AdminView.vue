<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import { useAuthStore } from '../stores/auth'
import { adminRepository } from '../repositories/adminRepository'
import { useToast } from '../composables/useToast'
import { formatBytes } from '../utils/documents'
import { formatDate } from '../utils/dates'
import type { AdminHousehold, AdminOverview, AdminUser } from '../types'

/**
 * Betreiber-Ansicht (Plattform-Admin): Kennzahlen, Haushalte mit Tarif, Nutzer sperren.
 * Bewusst schlicht — ein Werkzeug für den Betrieb, kein Dashboard für Haushaltsinhalte.
 */
const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()
const { notifySuccess, notifyError } = useToast()

const overview = ref<AdminOverview | null>(null)
const householdQuery = ref('')
const households = ref<AdminHousehold[]>([])
const userQuery = ref('')
const users = ref<AdminUser[]>([])
const busyId = ref<string | null>(null)
const planExpiry = ref<Record<string, string>>({})

async function loadOverview() {
  try {
    overview.value = await adminRepository.fetchOverview()
  } catch (error) {
    notifyError(t('admin.loadError'), error)
  }
}

async function searchHouseholds() {
  try {
    households.value = await adminRepository.searchHouseholds(householdQuery.value.trim())
  } catch (error) {
    notifyError(t('admin.loadError'), error)
  }
}

async function searchUsers() {
  try {
    users.value = await adminRepository.searchUsers(userQuery.value.trim())
  } catch (error) {
    notifyError(t('admin.loadError'), error)
  }
}

async function setPlan(h: AdminHousehold, plan: 'free' | 'premium') {
  busyId.value = h.id
  try {
    const expiry = planExpiry.value[h.id]
    const expiresAt = plan === 'premium' && expiry ? new Date(`${expiry}T23:59:59`).toISOString() : null
    const updated = await adminRepository.setPlan(h.id, plan, expiresAt, '')
    households.value = households.value.map(x => (x.id === updated.id ? updated : x))
    notifySuccess(t('admin.planSaved'))
    loadOverview()
  } catch (error) {
    notifyError(t('admin.saveError'), error)
  } finally {
    busyId.value = null
  }
}

async function setActive(u: AdminUser, isActive: boolean) {
  busyId.value = u.id
  try {
    const updated = await adminRepository.setUserActive(u.id, isActive)
    users.value = users.value.map(x => (x.id === updated.id ? updated : x))
    notifySuccess(isActive ? t('admin.userActivated') : t('admin.userDeactivated'))
  } catch (error) {
    notifyError(t('admin.saveError'), error)
  } finally {
    busyId.value = null
  }
}

onMounted(async () => {
  await authStore.authReady
  if (!authStore.user?.is_platform_admin) {
    router.replace('/dashboard')
    return
  }
  await Promise.all([loadOverview(), searchHouseholds(), searchUsers()])
})
</script>

<template>
  <div class="admin-page">
    <PageHeader :title="t('admin.title')" />

    <BaseCard v-if="overview">
      <h2 class="section-title">{{ t('admin.overview') }}</h2>
      <ul class="admin-stats">
        <li>{{ t('admin.usersTotal') }}: {{ overview.users_total }} ({{ t('admin.usersActive') }}: {{ overview.users_active }}, {{ t('admin.usersDeleted') }}: {{ overview.users_deleted }})</li>
        <li>{{ t('admin.householdsTotal') }}: {{ overview.households_total }}</li>
        <li v-if="overview.billing_enabled">
          {{ t('admin.byPlan') }}:
          <span v-for="(count, plan) in overview.households_by_plan" :key="plan" class="admin-chip">{{ t(`billing.plan.${plan}`) }} {{ count }}</span>
          · {{ t('admin.subscriptionsActive') }}: {{ overview.subscriptions_active }}
        </li>
        <li v-else>{{ t('admin.billingOff') }}</li>
      </ul>
    </BaseCard>

    <BaseCard>
      <h2 class="section-title">{{ t('admin.households') }}</h2>
      <form class="admin-search" @submit.prevent="searchHouseholds">
        <BaseInput v-model="householdQuery" :placeholder="t('admin.householdSearch')" />
        <BaseButton type="submit" variant="secondary" size="sm">{{ t('common.search') }}</BaseButton>
      </form>
      <ul class="admin-list">
        <li v-for="h in households" :key="h.id" class="admin-item">
          <div class="admin-item__main">
            <strong>{{ h.name }}</strong>
            <small>{{ h.id }} · {{ t('admin.members', { count: h.member_count }) }} · {{ formatBytes(h.storage_bytes) }} · {{ formatDate(h.created_at) }}</small>
            <small v-if="overview?.billing_enabled">
              {{ t('billing.plan.' + h.effective_plan) }}
              <template v-if="h.plan_expires_at"> ({{ t('billing.validUntil', { date: formatDate(h.plan_expires_at) }) }})</template>
              <template v-if="h.stripe_customer_id"> · Stripe {{ h.stripe_customer_id }}</template>
            </small>
          </div>
          <div v-if="overview?.billing_enabled" class="admin-item__actions">
            <input v-model="planExpiry[h.id]" type="date" class="admin-date" :aria-label="t('admin.planExpiry')" />
            <BaseButton variant="primary" size="sm" :loading="busyId === h.id" @click="setPlan(h, 'premium')">{{ t('admin.setPremium') }}</BaseButton>
            <BaseButton variant="ghost" size="sm" :loading="busyId === h.id" @click="setPlan(h, 'free')">{{ t('admin.setFree') }}</BaseButton>
          </div>
        </li>
      </ul>
      <p v-if="households.length === 0" class="section-hint">{{ t('common.noResults') }}</p>
    </BaseCard>

    <BaseCard>
      <h2 class="section-title">{{ t('admin.users') }}</h2>
      <form class="admin-search" @submit.prevent="searchUsers">
        <BaseInput v-model="userQuery" :placeholder="t('admin.userSearch')" />
        <BaseButton type="submit" variant="secondary" size="sm">{{ t('common.search') }}</BaseButton>
      </form>
      <ul class="admin-list">
        <li v-for="u in users" :key="u.id" class="admin-item">
          <div class="admin-item__main">
            <strong>{{ u.display_name }}</strong> <span>{{ u.email }}</span>
            <small>
              {{ formatDate(u.created_at) }} · {{ t('admin.households') }}: {{ u.household_count }}
              <template v-if="u.email_verified"> · {{ t('admin.verified') }}</template>
              <template v-if="u.is_platform_admin"> · {{ t('admin.platformAdmin') }}</template>
              <template v-if="u.deleted"> · {{ t('admin.deleted') }}</template>
              <template v-else-if="!u.is_active"> · {{ t('admin.disabled') }}</template>
            </small>
          </div>
          <div v-if="!u.deleted && u.id !== authStore.user?.id" class="admin-item__actions">
            <BaseButton v-if="u.is_active" variant="ghost" size="sm" :loading="busyId === u.id" @click="setActive(u, false)">{{ t('admin.deactivate') }}</BaseButton>
            <BaseButton v-else variant="secondary" size="sm" :loading="busyId === u.id" @click="setActive(u, true)">{{ t('admin.activate') }}</BaseButton>
          </div>
        </li>
      </ul>
      <p v-if="users.length === 0" class="section-hint">{{ t('common.noResults') }}</p>
    </BaseCard>
  </div>
</template>

<style scoped>
.admin-page {
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

.section-hint {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.admin-stats {
  margin: 0;
  padding-left: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text);
}

.admin-chip {
  display: inline-block;
  margin-right: var(--space-2);
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--chip);
}

.admin-search {
  display: flex;
  gap: var(--space-2);
  align-items: flex-end;
  margin-bottom: var(--space-3);
}

.admin-search > :first-child {
  flex: 1;
}

.admin-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.admin-item {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-top: 1px solid var(--color-border);
}

.admin-item__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  font-size: var(--text-sm);
}

.admin-item__main small {
  color: var(--color-text-secondary);
  word-break: break-all;
}

.admin-item__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.admin-date {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: var(--text-sm);
}
</style>
