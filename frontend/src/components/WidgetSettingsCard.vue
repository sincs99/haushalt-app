<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhCopy, PhDeviceMobile, PhDownloadSimple } from '@phosphor-icons/vue'
import BaseCard from './ui/BaseCard.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseDialog from './ui/BaseDialog.vue'
import { API_BASE } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'
import { createOnlineWidgetRepository } from '../repositories/widgetRepository'
import { useWidgetToken } from '../composables/useWidgetToken'
import { buildWidgetScript } from '../utils/widgetScript'
import { translateApiError } from '../utils/apiErrors'
import { formatDate } from '../utils/dates'

/**
 * Homescreen-Widget (Scriptable auf dem iPhone): Nur-Lese-Schlüssel erzeugen,
 * fertiges Skript kopieren, Schlüssel widerrufen. Doku: docs/widget.md
 */
const { t, locale } = useI18n()
const { showToast } = useToast()
const authStore = useAuthStore()
const repo = createOnlineWidgetRepository()

const confirmRevoke = ref(false)
const confirmReplace = ref(false)

const householdId = computed(() => authStore.currentHouseholdId)

// Antworten für einen inzwischen gewechselten Haushalt werden verworfen (CASA-50)
const { status, script, busy, load, create: createToken, revoke: revokeToken } = useWidgetToken(
  householdId,
  repo,
  (token) => buildWidgetScript(API_BASE || window.location.origin, token, locale.value),
  (error) => showToast(translateApiError(error), 'error'),
)

onMounted(load)

async function create() {
  confirmReplace.value = false
  await createToken()
}

async function revoke() {
  confirmRevoke.value = false
  if (await revokeToken()) showToast(t('widget.revoked'), 'success')
}

async function copyScript() {
  if (!script.value) return
  try {
    await navigator.clipboard.writeText(script.value)
    showToast(t('widget.copied'), 'success')
  } catch {
    showToast(t('widget.copyFailed'), 'error')
  }
}

function downloadScript() {
  if (!script.value) return
  const url = URL.createObjectURL(new Blob([script.value], { type: 'text/javascript' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'Haushalt.js'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <BaseCard>
    <template #header>
      <span class="widget-card__title">
        <PhDeviceMobile :size="20" />
        {{ t('widget.title') }}
      </span>
    </template>

    <p class="widget-card__hint">{{ t('widget.hint') }}</p>

    <!-- Direkt nach dem Erzeugen: Skript mit Schlüssel (nur jetzt sichtbar) -->
    <div v-if="script" class="widget-card__script">
      <p class="widget-card__warning">{{ t('widget.onlyNow') }}</p>
      <ol class="widget-card__steps">
        <li>{{ t('widget.step1') }}</li>
        <li>{{ t('widget.step2') }}</li>
        <li>{{ t('widget.step3') }}</li>
      </ol>
      <div class="widget-card__actions">
        <BaseButton size="sm" @click="copyScript">
          <PhCopy :size="16" />
          {{ t('widget.copy') }}
        </BaseButton>
        <BaseButton variant="secondary" size="sm" @click="downloadScript">
          <PhDownloadSimple :size="16" />
          {{ t('widget.download') }}
        </BaseButton>
      </div>
      <textarea
        class="widget-card__code"
        :value="script"
        readonly
        rows="6"
        :aria-label="t('widget.scriptLabel')"
        @focus="($event.target as HTMLTextAreaElement).select()"
      />
    </div>

    <template v-else-if="status?.exists">
      <p class="widget-card__state">
        {{ t('widget.active', { prefix: status.token_prefix }) }}
      </p>
      <p class="widget-card__meta">
        {{ t('widget.createdAt', { date: formatDate(status.created_at!) }) }}
        ·
        {{ status.last_used_at
          ? t('widget.lastUsed', { date: formatDate(status.last_used_at) })
          : t('widget.neverUsed') }}
      </p>
    </template>

    <div class="widget-card__actions">
      <BaseButton
        v-if="!status?.exists"
        size="sm"
        :loading="busy"
        @click="create"
      >
        {{ t('widget.create') }}
      </BaseButton>
      <template v-else>
        <BaseButton variant="secondary" size="sm" :disabled="busy" @click="confirmReplace = true">
          {{ t('widget.replace') }}
        </BaseButton>
        <BaseButton variant="ghost" size="sm" :disabled="busy" @click="confirmRevoke = true">
          {{ t('widget.revoke') }}
        </BaseButton>
      </template>
    </div>

    <BaseDialog :open="confirmReplace" :title="t('widget.replace')" @close="confirmReplace = false">
      <p class="widget-card__dialog-text">{{ t('widget.replaceConfirm') }}</p>
      <template #footer>
        <BaseButton variant="secondary" @click="confirmReplace = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton :loading="busy" @click="create">{{ t('widget.replace') }}</BaseButton>
      </template>
    </BaseDialog>

    <BaseDialog :open="confirmRevoke" :title="t('widget.revoke')" danger @close="confirmRevoke = false">
      <p class="widget-card__dialog-text">{{ t('widget.revokeConfirm') }}</p>
      <template #footer>
        <BaseButton variant="secondary" @click="confirmRevoke = false">{{ t('common.cancel') }}</BaseButton>
        <BaseButton variant="danger" :loading="busy" @click="revoke">{{ t('widget.revoke') }}</BaseButton>
      </template>
    </BaseDialog>
  </BaseCard>
</template>

<style scoped>
.widget-card__title {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.widget-card__hint,
.widget-card__meta,
.widget-card__dialog-text {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--sub);
}

.widget-card__dialog-text {
  margin: 0;
  color: var(--ink);
}

.widget-card__state {
  margin: 0 0 var(--space-1);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.widget-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.widget-card__script {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-btn);
  background: var(--chip);
}

.widget-card__warning {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-warning-strong);
}

.widget-card__steps {
  margin: 0;
  padding-left: var(--space-5);
  font-size: var(--text-sm);
  color: var(--ink);
  line-height: var(--line-height-normal);
}

.widget-card__code {
  width: 100%;
  padding: var(--space-2);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  background: var(--card);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  resize: vertical;
}
</style>
