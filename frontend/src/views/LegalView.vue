<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import BaseCard from '../components/ui/BaseCard.vue'
import { useAuthStore } from '../stores/auth'
import { useConfigStore } from '../stores/config'
import { fillPlaceholders, renderMarkdown } from '../utils/markdown'

/**
 * Rechtstexte (/legal/imprint|privacy|terms). Die Texte liegen als Markdown unter
 * public/legal/<seite>.<sprache>.md; Betreiber ersetzen sie durch eigene Dateien
 * (Docker: Volume auf /usr/share/nginx/html/legal). Platzhalter {{operator.*}}
 * kommen aus /api/config (OPERATOR_NAME, OPERATOR_ADDRESS, OPERATOR_EMAIL).
 */
const PAGES = ['imprint', 'privacy', 'terms'] as const
type Page = (typeof PAGES)[number]

const route = useRoute()
const authStore = useAuthStore()
const configStore = useConfigStore()
const { locale, t } = useI18n()

const page = computed<Page>(() => (PAGES.includes(route.params.page as Page) ? (route.params.page as Page) : 'imprint'))
const html = ref('')
const state = ref<'loading' | 'ready' | 'error'>('loading')

async function load() {
  state.value = 'loading'
  await configStore.load()
  const lang = locale.value.startsWith('en') ? 'en' : 'de'
  try {
    const response = await fetch(`/legal/${page.value}.${lang}.md`, { cache: 'no-cache' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const operator = configStore.config.operator
    const source = fillPlaceholders(await response.text(), {
      'operator.name': operator.name || t('legal.operatorMissing'),
      'operator.address': operator.address_lines.join('\n') || t('legal.operatorMissing'),
      'operator.email': operator.email || t('legal.operatorMissing'),
      'terms.version': configStore.config.terms_version,
    })
    html.value = renderMarkdown(source)
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}

onMounted(load)
watch([page, locale], load)
</script>

<template>
  <div class="legal-page" :class="{ 'legal-page--public': !authStore.isAuthenticated }">
    <nav class="legal-nav" :aria-label="t('legal.title')">
      <router-link v-for="p in PAGES" :key="p" :to="`/legal/${p}`" class="legal-nav__link" active-class="legal-nav__link--active">
        {{ t(`legal.${p}`) }}
      </router-link>
    </nav>
    <BaseCard padding="lg">
      <p v-if="state === 'loading'" class="legal-hint">{{ t('common.loading') }}</p>
      <p v-else-if="state === 'error'" class="legal-hint" role="alert">{{ t('legal.loadError') }}</p>
      <!-- eslint-disable-next-line vue/no-v-html — Inhalt stammt aus renderMarkdown (escaped) -->
      <article v-else class="legal-content" v-html="html" />
    </BaseCard>
    <p v-if="!authStore.isAuthenticated" class="legal-back">
      <router-link to="/login">{{ t('account.backToLogin') }}</router-link>
    </p>
  </div>
</template>

<style scoped>
.legal-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.legal-page--public {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-4);
}

.legal-nav {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.legal-nav__link {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--chip);
  color: var(--color-text);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  text-decoration: none;
}

.legal-nav__link--active {
  background: var(--color-primary);
  color: var(--color-on-primary, #fff);
}

.legal-hint,
.legal-back {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  text-align: center;
}

.legal-content {
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--color-text);
}

.legal-content :deep(h1) {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  margin: 0 0 var(--space-3);
}

.legal-content :deep(h2) {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  margin: var(--space-5) 0 var(--space-2);
}

.legal-content :deep(h3) {
  font-size: var(--text-base);
  margin: var(--space-4) 0 var(--space-2);
}

.legal-content :deep(p),
.legal-content :deep(ul) {
  margin: 0 0 var(--space-3);
}

.legal-content :deep(a) {
  color: var(--color-primary);
}
</style>
