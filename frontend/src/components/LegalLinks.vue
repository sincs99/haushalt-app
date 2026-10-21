<script setup lang="ts">
import { useI18n } from 'vue-i18n'

/** Fusszeile mit Impressum, Datenschutz und AGB (Anmelde-/Registrierseiten, Einstellungen). */
const { t } = useI18n()
</script>

<template>
  <p class="legal-links">
    <router-link to="/legal/imprint">{{ t('legal.imprint') }}</router-link>
    <span aria-hidden="true">·</span>
    <router-link to="/legal/privacy">{{ t('legal.privacy') }}</router-link>
    <span aria-hidden="true">·</span>
    <router-link to="/legal/terms">{{ t('legal.terms') }}</router-link>
  </p>
</template>

<style scoped>
.legal-links {
  display: flex;
  justify-content: center;
  gap: var(--space-2);
  margin: var(--space-4) 0 0;
  font-size: var(--text-xs, 0.75rem);
  color: var(--color-text-secondary);
}

.legal-links a {
  color: inherit;
  text-decoration: underline;
}
</style>
