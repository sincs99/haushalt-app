<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseButton from './ui/BaseButton.vue'
import { useToast } from '../composables/useToast'
import {
  getPushSupport,
  getPermission,
  getCurrentSubscription,
  enablePush,
  disablePush,
  sendTestPush,
  PushError,
} from '../services/pushService'

const { t } = useI18n()
const { notifySuccess, notifyError, notifyInfo } = useToast()

const support = getPushSupport()
const permission = ref<NotificationPermission>(getPermission())
const subscribed = ref(false)
const busy = ref(false)
const testing = ref(false)

const hint = computed(() => {
  if (support === 'ios-needs-install') return t('push.iosInstallHint')
  if (support === 'unsupported') return t('push.unsupported')
  if (permission.value === 'denied') return t('push.denied')
  return t('push.hint')
})

const canToggle = computed(() => support === 'supported' && permission.value !== 'denied')

onMounted(async () => {
  if (support !== 'supported') return
  subscribed.value = permission.value === 'granted' && !!(await getCurrentSubscription())
})

async function toggle() {
  if (busy.value) return
  // Ohne Netz kann der Server die Anmeldung nicht speichern
  if (navigator.onLine === false) {
    notifyInfo(t('offline.actionBlocked'))
    return
  }
  busy.value = true
  try {
    if (subscribed.value) {
      await disablePush()
      subscribed.value = false
      notifySuccess(t('push.disabled'))
    } else {
      await enablePush()
      subscribed.value = true
      notifySuccess(t('push.enabled'))
    }
  } catch (err) {
    if (err instanceof PushError && err.code === 'disabled') {
      notifyError(t('push.serverDisabled'))
    } else if (!(err instanceof PushError && err.code === 'denied')) {
      notifyError(t('push.error'), err)
    }
  } finally {
    permission.value = getPermission()
    busy.value = false
  }
}

async function sendTest() {
  if (testing.value) return
  if (navigator.onLine === false) {
    notifyInfo(t('offline.actionBlocked'))
    return
  }
  testing.value = true
  try {
    await sendTestPush()
    notifySuccess(t('push.testSent'))
  } catch (err) {
    notifyError(t('push.error'), err)
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="push-settings">
    <div class="settings-row">
      <span class="settings-label">{{ $t('push.title') }}</span>
      <BaseButton
        v-if="canToggle"
        :variant="subscribed ? 'secondary' : 'primary'"
        size="sm"
        :loading="busy"
        @click="toggle"
      >
        {{ subscribed ? $t('push.disable') : $t('push.enable') }}
      </BaseButton>
    </div>
    <p class="push-settings__hint">{{ hint }}</p>
    <BaseButton v-if="subscribed" variant="ghost" size="sm" :loading="testing" @click="sendTest">
      {{ $t('push.test') }}
    </BaseButton>
  </div>
</template>

<style scoped>
.push-settings {
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid var(--line);
}

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

.push-settings__hint {
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  margin: var(--space-2) 0;
}
</style>
