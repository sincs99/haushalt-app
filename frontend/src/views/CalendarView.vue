<script setup lang="ts">
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import { PhCalendarBlank } from '@phosphor-icons/vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <BaseEmptyState
    :icon="PhCalendarBlank"
    :title="t('calendar.emptyTitle')"
    :subtitle="t('calendar.emptySubtitle')"
  />
</template>
