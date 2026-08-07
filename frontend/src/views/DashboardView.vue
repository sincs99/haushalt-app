<script setup lang="ts">
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import { PhWrench } from '@phosphor-icons/vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <BaseEmptyState
    :icon="PhWrench"
    :title="t('dashboard.emptyTitle')"
    :subtitle="t('dashboard.emptySubtitle')"
  />
</template>
