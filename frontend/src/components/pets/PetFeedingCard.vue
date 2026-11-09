<script setup lang="ts">
/**
 * „Fütterung heute“ auf der Tier-Detailseite: Morgen/Abend abhaken bzw. entfernen,
 * inkl. Rückfrage beim Entfernen der Fütterung einer anderen Person (CASA-30).
 * Archivierte Tiere zeigen keine Karte (der Rückfrage-Dialog bleibt bedienbar).
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePetsStore } from '../../stores/pets'
import { useAuthStore } from '../../stores/auth'
import { useToast } from '../../composables/useToast'
import { useAsyncAction } from '../../composables/useAsyncAction'
import { formatClock, needsUnfeedConfirmation } from '../../utils/petCare'
import type { Pet, FeedingSlot } from '../../types'
import { PhSun, PhMoon } from '@phosphor-icons/vue'
import BaseCard from '../ui/BaseCard.vue'
import BaseButton from '../ui/BaseButton.vue'
import BaseDialog from '../ui/BaseDialog.vue'

const props = defineProps<{
  pet: Pet
}>()

const petsStore = usePetsStore()
const authStore = useAuthStore()
const { notifyInfo } = useToast()
const { run } = useAsyncAction()
const { t } = useI18n()

const feedingStatus = computed(() =>
  petsStore.feedingStatus.find(s => s.pet_id === props.pet.id),
)

function getMemberName(userId: string): string {
  const member = petsStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.unknown')
}

function formatFeedingTime(fedAt: string): string {
  const d = new Date(fedAt)
  return d.toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
}

function isFed(slot: FeedingSlot): boolean {
  if (!feedingStatus.value) return false
  return !!feedingStatus.value[slot]
}

function feedingSlotInfo(slot: FeedingSlot): string | null {
  const fs = feedingStatus.value
  if (!fs) return null
  const entry = fs[slot]
  if (!entry) return null
  return t('pets.fedAt', {
    slot: t(`pets.${slot}`),
    time: formatFeedingTime(entry.fed_at),
    name: getMemberName(entry.fed_by_user_id),
  })
}

// Fütterung einer anderen Person entfernen → erst nachfragen (wer, wann; CASA-30)
const unfeedConfirmSlot = ref<FeedingSlot | null>(null)
const unfeedConfirmText = computed(() => {
  const entry = unfeedConfirmSlot.value ? feedingStatus.value?.[unfeedConfirmSlot.value] : null
  if (!entry) return ''
  return t('pets.unfeedOtherHint', {
    name: getMemberName(entry.fed_by_user_id),
    time: formatClock(entry.fed_at),
    pet: props.pet.name,
  })
})

function handleToggleFeeding(slot: FeedingSlot) {
  if (needsUnfeedConfirmation(feedingStatus.value?.[slot], authStore.user?.id)) {
    unfeedConfirmSlot.value = slot
    return
  }
  return toggleFeeding(slot)
}

function confirmUnfeed() {
  const slot = unfeedConfirmSlot.value
  unfeedConfirmSlot.value = null
  if (slot) return toggleFeeding(slot)
}

function toggleFeeding(slot: FeedingSlot) {
  const id = props.pet.id
  const name = props.pet.name
  return run(async () => {
    const result = await petsStore.toggleFeeding(id, slot)
    // 409: schon gefüttert (Status wurde neu geladen) → Hinweis, kein Fehler
    if (result === 'duplicate') notifyInfo(t('errors.FEEDING_DUPLICATE'))
    return result
  }, {
    key: `feed-${slot}`,
    // Nur fürs Füttern; Entfernen ist selbst schon das Rückgängigmachen
    success: (result) => (result === 'fed' ? t('pets.fedToast', { name }) : undefined),
    undo: () => petsStore.toggleFeeding(id, slot),
    error: t('pets.feedError'),
  })
}
</script>

<template>
  <!-- ═══ Fütterung heute ═══ (nicht für archivierte Tiere) -->
  <section v-if="!pet.archived" class="section">
    <BaseCard>
      <h2 class="card-title">{{ $t('pets.feedingToday') }}</h2>

      <div class="feeding-detail">
        <div class="feeding-detail__row">
          <div class="feeding-detail__info">
            <span class="feeding-detail__slot-label">{{ $t('pets.morning') }}</span>
            <span v-if="feedingSlotInfo('morning')" class="feeding-detail__text">
              {{ feedingSlotInfo('morning') }}
            </span>
            <span v-else class="feeding-detail__text feeding-detail__text--empty">
              {{ $t('pets.notFedYet') }}
            </span>
          </div>
          <button
            type="button"
            class="feed-toggle tap-target"
            :class="{ 'feed-toggle--fed': isFed('morning') }"
            :title="$t('pets.feedToggleMorning', { name: pet.name })"
            :aria-label="$t('pets.feedToggleMorning', { name: pet.name })"
            :aria-pressed="isFed('morning')"
            @click="handleToggleFeeding('morning')"
          >
            <PhSun :size="16" weight="bold" />
          </button>
        </div>

        <div class="feeding-detail__row">
          <div class="feeding-detail__info">
            <span class="feeding-detail__slot-label">{{ $t('pets.evening') }}</span>
            <span v-if="feedingSlotInfo('evening')" class="feeding-detail__text">
              {{ feedingSlotInfo('evening') }}
            </span>
            <span v-else class="feeding-detail__text feeding-detail__text--empty">
              {{ $t('pets.notFedYet') }}
            </span>
          </div>
          <button
            type="button"
            class="feed-toggle tap-target"
            :class="{ 'feed-toggle--fed': isFed('evening') }"
            :title="$t('pets.feedToggleEvening', { name: pet.name })"
            :aria-label="$t('pets.feedToggleEvening', { name: pet.name })"
            :aria-pressed="isFed('evening')"
            @click="handleToggleFeeding('evening')"
          >
            <PhMoon :size="16" weight="bold" />
          </button>
        </div>
      </div>
    </BaseCard>
  </section>

  <!-- ═══ Fütterung einer anderen Person entfernen (CASA-30) ═══ -->
  <BaseDialog
    :open="!!unfeedConfirmSlot"
    :title="$t('pets.unfeedOtherTitle')"
    @close="unfeedConfirmSlot = null"
  >
    <p class="dialog-hint">{{ unfeedConfirmText }}</p>
    <template #footer>
      <div class="dialog-actions">
        <BaseButton variant="ghost" @click="unfeedConfirmSlot = null">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton variant="danger" @click="confirmUnfeed">
          {{ $t('pets.unfeedOtherConfirm') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>
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

/* ── Feeding Detail ── */
.feeding-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.feeding-detail__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line);
}

.feeding-detail__row:last-child {
  border-bottom: none;
}

.feeding-detail__info {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  flex: 1;
  min-width: 0;
}

.feeding-detail__slot-label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.feeding-detail__text {
  font-size: var(--text-xs);
  color: var(--sub);
}

.feeding-detail__text--empty {
  font-style: italic;
}

/* ── Feed Toggle Buttons (reused from PetsView) ── */
.feed-toggle {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-full);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--chip);
  color: var(--sub);
  transition: background var(--transition-fast), color var(--transition-fast);
  flex-shrink: 0;
}

.feed-toggle:active {
  transform: scale(0.92);
}

.feed-toggle--fed {
  background: var(--ok);
  color: var(--color-on-success);
}

/* ── Dialog ── */
.dialog-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  color: var(--sub);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
