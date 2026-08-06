<script setup lang="ts">
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import { translateApiError } from '../utils/apiErrors'
import { Home } from 'lucide-vue-next'

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
      <h1 class="auth-title"><Home :size="24" /> {{ $t('auth.appTitle') }}</h1>
      <p class="auth-subtitle">{{ $t('auth.registerSubtitle') }}</p>

      <!-- Tab-Umschalter -->
      <div class="register-tabs">
        <button
          class="register-tab"
          :class="{ 'register-tab--active': mode === 'create' }"
          @click="mode = 'create'"
        >
          {{ $t('auth.tabCreate') }}
        </button>
        <button
          class="register-tab"
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

<style scoped>
.auth-page {
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  background: var(--color-bg);
}

.auth-card {
  width: 100%;
  max-width: 400px;
}

.auth-title {
  margin: 0 0 var(--space-1);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-bold);
  text-align: center;
  color: var(--color-text);
}

.auth-subtitle {
  margin: 0 0 var(--space-6);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-align: center;
}

.register-tabs {
  display: flex;
  gap: var(--space-1);
  margin-bottom: var(--space-4);
  background: var(--color-neutral-100);
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
  transition: all 0.15s ease;
}

.register-tab--active {
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: var(--shadow-sm);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.auth-error {
  margin: 0;
  padding: var(--space-3);
  background: var(--color-danger-light);
  border: 1px solid #FECACA;
  border-radius: var(--radius-sm);
  color: var(--color-danger);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
}

.auth-submit {
  width: 100%;
}

.auth-link {
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin: 0;
}

.auth-link a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: var(--font-weight-medium);
}

.auth-link a:hover {
  text-decoration: underline;
}
</style>
