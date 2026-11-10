<script setup lang="ts">
/**
 * „Über {Name}“ auf der Tier-Detailseite: Steckbrief, Gesundheitseinträge und der
 * Archivieren-Knopf. Archiviert wird beim Aufrufer (`archive`), der auch `archiving` meldet.
 */
import { useI18n } from 'vue-i18n'
import type { Pet } from '../../types'
import BaseCard from '../ui/BaseCard.vue'
import BaseButton from '../ui/BaseButton.vue'

defineProps<{
  pet: Pet
  archiving: boolean
}>()

const emit = defineEmits<{
  archive: []
}>()

const { t } = useI18n()

// ── Pet Info Helpers ──

function calculateAge(birthdate: string | null): string | null {
  if (!birthdate) return null
  const birth = new Date(birthdate)
  const now = new Date()
  let age = now.getFullYear() - birth.getFullYear()
  if (now.getMonth() < birth.getMonth() ||
    (now.getMonth() === birth.getMonth() && now.getDate() < birth.getDate())) {
    age--
  }
  return t('pets.age', { n: age })
}
</script>

<template>
  <!-- ═══ Über {Name} ═══ -->
  <section class="section">
    <BaseCard>
      <h2 class="card-title">{{ $t('pets.about', { name: pet.name }) }}</h2>

      <div class="fact-list">
        <div v-if="pet.breed" class="fact-row">
          <span class="fact-label">{{ $t('pets.breed') }}</span>
          <span class="fact-value">{{ pet.breed }}</span>
        </div>
        <div v-if="calculateAge(pet.birthdate)" class="fact-row">
          <span class="fact-label">{{ $t('pets.birthdateLabel') }}</span>
          <span class="fact-value">{{ calculateAge(pet.birthdate) }}</span>
        </div>
        <div v-if="pet.weight_grams" class="fact-row">
          <span class="fact-label">{{ $t('pets.weight') }}</span>
          <span class="fact-value">{{ (pet.weight_grams / 1000).toFixed(1) }} kg</span>
        </div>
        <div v-if="pet.chip_number" class="fact-row">
          <span class="fact-label">{{ $t('pets.chipNumber') }}</span>
          <span class="fact-value">{{ pet.chip_number }}</span>
        </div>
        <div v-if="pet.insurance" class="fact-row">
          <span class="fact-label">{{ $t('pets.insurance') }}</span>
          <span class="fact-value">{{ pet.insurance }}</span>
        </div>
        <div v-if="pet.vet_name" class="fact-row">
          <span class="fact-label">{{ $t('pets.vetName') }}</span>
          <span class="fact-value">{{ pet.vet_name }}</span>
        </div>
        <div v-if="pet.food_notes" class="fact-row">
          <span class="fact-label">{{ $t('pets.foodNotes') }}</span>
          <span class="fact-value">{{ pet.food_notes }}</span>
        </div>
        <div v-if="pet.notes" class="fact-row">
          <span class="fact-label">{{ $t('pets.notes') }}</span>
          <span class="fact-value">{{ pet.notes }}</span>
        </div>
      </div>

      <!-- Gesundheitseinträge -->
      <div v-if="pet.health_entries?.length" class="health-section">
        <h4 class="health-title">{{ $t('pets.health') }}</h4>
        <div v-for="(entry, i) in pet.health_entries" :key="i" class="health-entry">
          <span class="health-dot" :class="'health-dot--' + entry.severity" />
          <div class="health-text">
            <span class="health-entry-title">{{ entry.title }}</span>
            <span class="health-entry-subtitle">{{ entry.subtitle }}</span>
          </div>
        </div>
      </div>

      <!-- Archivieren (verstorben/abgegeben): Verlauf bleibt erhalten -->
      <div v-if="!pet.archived" class="archive-action">
        <BaseButton variant="ghost" size="sm" :loading="archiving" @click="emit('archive')">
          {{ $t('pets.archive') }}
        </BaseButton>
        <span class="archive-action__hint">{{ $t('pets.archiveActionHint') }}</span>
      </div>
    </BaseCard>
  </section>
</template>

<style scoped>
/* ── Section ── */
.section {
  margin-bottom: var(--space-4);
}

/* ── Card Title ── */
.card-title {
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  margin: 0 0 var(--space-3) 0;
  color: var(--ink);
}

.archive-action {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--line);
}

.archive-action__hint {
  font-size: var(--text-xs);
  color: var(--sub);
}

/* ── Fact List ── */
.fact-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.fact-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-3);
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--line);
}

.fact-row:last-child {
  border-bottom: none;
}

.fact-label {
  font-size: var(--text-sm);
  color: var(--sub);
  font-weight: var(--font-weight-medium);
  flex-shrink: 0;
}

.fact-value {
  font-size: var(--text-sm);
  color: var(--ink);
  text-align: right;
  word-break: break-word;
}

/* ── Health Section ── */
.health-section {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--line);
}

.health-title {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0 0 var(--space-3) 0;
}

.health-entry {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) 0;
}

.health-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 5px;
}

.health-dot--green { background: var(--ok); }
.health-dot--yellow { background: var(--color-warning); }
.health-dot--red { background: var(--color-danger); }

.health-text {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
}

.health-entry-title {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.health-entry-subtitle {
  font-size: var(--text-xs);
  color: var(--sub);
}
</style>
