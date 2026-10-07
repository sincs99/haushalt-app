<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import { translateApiError } from '../utils/apiErrors'
import { PhHouse } from '@phosphor-icons/vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { t } = useI18n()

// Registrierungs-Modus: 'create' oder 'join'
const mode = ref<'create' | 'join'>('create')

const email = ref('')
const password = ref('')
const displayName = ref('')
const householdName = ref('')
const inviteCode = ref('')
const error = ref('')
const isLoading = ref(false)

onMounted(() => {
  // Query-Parameter ?code=XYZ → automatisch Beitreten-Modus
  const code = route.query.code
  if (typeof code === 'string' && code.trim()) {
    mode.value = 'join'
    inviteCode.value = code.trim().toUpperCase()
  }
})

async function handleRegister() {
  error.value = ''
  isLoading.value = true
  try {
    if (mode.value === 'create') {
      await authStore.register(email.value, password.value, displayName.value, { householdName: householdName.value })
    } else {
      await authStore.register(email.value, password.value, displayName.value, { inviteCode: inviteCode.value.toUpperCase() })
    }
    router.push('/shopping')
  } catch (err: any) {
    error.value = translateApiError(err)
  } finally {
    isLoading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <BaseCard padding="lg" class="auth-card">
      <h1 class="auth-title"><PhHouse :size="24" /> {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('auth.registerSubtitle') }}</p>

      <!-- Tab-Umschalter -->
      <div class="register-tabs">
        <button
          class="register-tab tap-target"
          :class="{ 'register-tab--active': mode === 'create' }"
          @click="mode = 'create'"
        >
          {{ $t('auth.tabCreate') }}
        </button>
        <button
          class="register-tab tap-target"
          :class="{ 'register-tab--active': mode === 'join' }"
          @click="mode = 'join'"
        >
          {{ $t('auth.tabJoin') }}
        </button>
      </div>

      <form @submit.prevent="handleRegister" class="auth-form">
        <BaseInput v-model="email" :label="$t('auth.email')" type="email" :placeholder="$t('auth.emailPlaceholder')" autocomplete="email" />
        <BaseInput v-model="password" :label="$t('auth.password')" type="password" :placeholder="$t('auth.passwordMinLength')" autocomplete="new-password" />
        <BaseInput v-model="displayName" :label="$t('auth.displayName')" type="text" :placeholder="$t('auth.namePlaceholder')" autocomplete="name" />

        <!-- Modus-spezifische Felder -->
        <BaseInput
          v-if="mode === 'create'"
          v-model="householdName"
          :label="$t('auth.householdName')"
          type="text"
          :placeholder="$t('auth.householdPlaceholder')"
        />
        <BaseInput
          v-if="mode === 'join'"
          v-model="inviteCode"
          :label="$t('auth.inviteCodeLabel')"
          type="text"
          :placeholder="$t('auth.inviteCodePlaceholder')"
          style="text-transform: uppercase"
        />

        <p v-if="error" class="auth-error">{{ error }}</p>

        <BaseButton type="submit" variant="primary" :loading="isLoading" :disabled="isLoading" class="auth-submit">
          {{ $t('auth.register') }}
        </BaseButton>

        <p class="auth-link">
          {{ $t('auth.hasAccount') }} <router-link to="/login">{{ $t('auth.loginHere') }}</router-link>
        </p>
      </form>
    </BaseCard>
  </div>
</template>

<style scoped src="../assets/auth.css"></style>

<style scoped>
.register-tabs {
  display: flex;
  gap: var(--space-1);
  margin-bottom: var(--space-4);
  background: var(--chip);
  border-radius: var(--radius-md);
  padding: var(--space-1);
}

.register-tab {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-family: var(--font-family);
  transition: background var(--transition-fast), color var(--transition-fast), box-shadow var(--transition-fast);
}

.register-tab--active {
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: var(--shadow-sm);
}
</style>
