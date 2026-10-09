<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { PhCrown } from '@phosphor-icons/vue'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import { useAuthStore } from '../stores/auth'
import { useConfigStore } from '../stores/config'
import { billingRepository } from '../repositories/billingRepository'
import { useToast } from '../composables/useToast'
import { formatBytes } from '../utils/documents'
import { formatDate } from '../utils/dates'
import { isNativeApp } from '../services/platform'
import type { BillingStatus } from '../types'

/**
 * Haushaltseinstellungen → Tarif. Nur sichtbar im SaaS-Betrieb (BILLING_ENABLED).
 * Upgrade/Verwalten nur für Admins; in der nativen App gibt es keinen Stripe-Checkout
 * (Store-Abrechnung, docs/monetization.md).
 */
const authStore = useAuthStore()
const configStore = useConfigStore()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { notifySuccess, notifyInfo, notifyError } = useToast()

const status = ref<BillingStatus | null>(null)
const loading = ref(false)
const busy = ref(false)
const native = isNativeApp()

const isAdmin = computed(() => authStore.currentHousehold?.role === 'admin')
const visible = computed(() => configStore.config.billing_enabled)
const isPremium = computed(() => status.value?.plan === 'premium')
const canUpgrade = computed(() => !!status.value?.checkout_available && isAdmin.value && !isPremium.value && !native)
const canManage = computed(() => !!status.value?.portal_available && isAdmin.value && !native)

async function load() {
  if (!visible.value || !authStore.currentHouseholdId) return
  loading.value = true
  try {
    status.value = await billingRepository.fetchStatus(authStore.currentHouseholdId)
  } catch (error) {
    notifyError(t('billing.loadError'), error)
  } finally {
    loading.value = false
  }
}

async function upgrade(interval: 'month' | 'year') {
  if (busy.value || !authStore.currentHouseholdId) return
  busy.value = true
  try {
    const url = await billingRepository.startCheckout(authStore.currentHouseholdId, interval)
    window.location.assign(url)
  } catch (error) {
    notifyError(t('billing.checkoutError'), error)
    busy.value = false
  }
}

async function manage() {
  if (busy.value || !authStore.currentHouseholdId) return
  busy.value = true
  try {
    const url = await billingRepository.openPortal(authStore.currentHouseholdId)
    window.location.assign(url)
  } catch (error) {
    notifyError(t('billing.portalError'), error)
    busy.value = false
  }
}

function limitText(value: number | null, used: number): string {
  return value === null ? t('billing.unlimited', { used }) : t('billing.ofLimit', { used, limit: value })
}

onMounted(async () => {
  await configStore.load()
  // Rückkehr von Stripe (?billing=success|cancel): Meldung zeigen, Query entfernen
  const outcome = route.query.billing
  if (outcome === 'success') notifySuccess(t('billing.checkoutSuccess'))
  else if (outcome === 'cancel') notifyInfo(t('billing.checkoutCancelled'))
  if (outcome) {
    const query = { ...route.query }
    delete query.billing
    router.replace({ query })
  }
  await load()
})
watch(() => authStore.currentHouseholdId, load)
watch(() => authStore.currentHousehold?.plan, load)
</script>

<template>
  <BaseCard v-if="visible" id="billing">
    <h2 class="billing__title">
      <PhCrown :size="20" />
      {{ t('billing.title') }}
    </h2>

    <template v-if="status">
      <div class="billing__row">
        <span class="billing__plan" :class="{ 'billing__plan--premium': isPremium }">
          {{ t(`billing.plan.${status.plan}`) }}
        </span>
        <BaseButton v-if="canUpgrade" variant="primary" size="sm" :loading="busy" @click="upgrade(status.intervals.includes('month') ? 'month' : 'year')">
          {{ t('billing.upgrade') }}
        </BaseButton>
        <BaseButton v-else-if="canManage" variant="secondary" size="sm" :loading="busy" @click="manage">
          {{ t('billing.manage') }}
        </BaseButton>
      </div>

      <p v-if="canUpgrade && status.intervals.includes('year') && status.intervals.includes('month')" class="billing__hint">
        <button type="button" class="billing__link" :disabled="busy" @click="upgrade('year')">{{ t('billing.upgradeYearly') }}</button>
      </p>

      <ul class="billing__limits">
        <li>{{ t('billing.members') }}: {{ limitText(status.limits.max_members, status.usage.members) }}</li>
        <li>{{ t('billing.storage') }}: {{ t('billing.ofLimit', { used: formatBytes(status.usage.storage_bytes), limit: formatBytes(status.limits.storage_bytes) }) }}</li>
        <li>
          {{ t('billing.ai') }}:
          <template v-if="status.limits.ai_daily_limit > 0">{{ t('billing.aiPerDay', { limit: status.limits.ai_daily_limit }) }}</template>
          <template v-else>{{ t('billing.aiNotIncluded') }}</template>
        </li>
      </ul>

      <p v-if="status.subscription?.cancel_at_period_end && status.subscription.current_period_end" class="billing__hint">
        {{ t('billing.endsOn', { date: formatDate(status.subscription.current_period_end) }) }}
      </p>
      <p v-else-if="isPremium && status.subscription?.status === 'past_due'" class="billing__hint billing__hint--warning">
        {{ t('billing.pastDue') }}
      </p>
      <p v-else-if="isPremium && status.plan_expires_at && status.subscription?.provider === 'manual'" class="billing__hint">
        {{ t('billing.validUntil', { date: formatDate(status.plan_expires_at) }) }}
      </p>

      <p v-if="!isPremium && native" class="billing__hint">{{ t('billing.nativeHint') }}</p>
      <p v-else-if="!isPremium && !isAdmin" class="billing__hint">{{ t('billing.adminOnly') }}</p>
      <p v-else-if="!isPremium && !status.checkout_available" class="billing__hint">{{ t('billing.noCheckout') }}</p>
    </template>
    <p v-else-if="loading" class="billing__hint">{{ t('common.loading') }}</p>
  </BaseCard>
</template>

<style scoped>
.billing__title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.billing__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.billing__plan {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.billing__plan--premium {
  color: var(--color-primary);
}

.billing__limits {
  margin: var(--space-3) 0 0;
  padding-left: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.billing__hint {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.billing__hint--warning {
  color: var(--color-danger);
}

.billing__link {
  border: none;
  background: transparent;
  padding: 0;
  color: var(--color-primary);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
}
</style>
