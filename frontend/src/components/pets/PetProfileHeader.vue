<script setup lang="ts">
/**
 * Kopf der Tier-Detailseite: Foto (mit Upload), Zurück, Name/Art, Archiv-Badge und
 * Bearbeiten-Knopf. Bearbeitet wird im Dialog des Aufrufers (`edit`).
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { usePetsStore } from '../../stores/pets'
import { useAuthStore } from '../../stores/auth'
import { useToast } from '../../composables/useToast'
import { useProtectedImage } from '../../composables/useProtectedImage'
import { usePhotoUpload } from '../../composables/usePhotoUpload'
import { imageUploadErrorReason } from '../../utils/imageUpload'
import type { Pet } from '../../types'
import { PhArrowLeft, PhPencilSimple, PhCamera, PhCat } from '@phosphor-icons/vue'

const props = defineProps<{
  pet: Pet
}>()

const emit = defineEmits<{
  edit: []
}>()

const router = useRouter()
const petsStore = usePetsStore()
const authStore = useAuthStore()
const { showToast, notifyError } = useToast()
const { t } = useI18n()

// ── Photo Upload ──

const fileInputRef = ref<HTMLInputElement | null>(null)

const petId = computed(() => props.pet.id)
const householdId = computed(() => authStore.currentHouseholdId)
const photoFileId = computed(() => props.pet.photo_file_id ?? null)
const { objectUrl: photoObjectUrl } = useProtectedImage(householdId, photoFileId)

const { uploading: photoUploading, upload: uploadPhoto } = usePhotoUpload({
  householdId,
  entityId: petId,
  fileId: photoFileId,
  update: (hid, id, fileId) => petsStore.updatePet(id, { photo_file_id: fileId }, hid),
})

async function handlePhotoUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    if (await uploadPhoto(file)) showToast(t('pets.photoUploadSuccess'), 'success')
  } catch (error) {
    notifyError(t('pets.photoUploadErrorReason', { reason: imageUploadErrorReason(error) }))
  }
}

function speciesEmoji(species: string): string {
  switch (species) {
    case 'cat': return '🐱'
    case 'dog': return '🐶'
    case 'bird': return '🐦'
    case 'fish': return '🐟'
    case 'rabbit': return '🐰'
    default: return '🐾'
  }
}
</script>

<template>
  <!-- ═══ Foto-Bereich ═══ -->
  <div class="pet-photo-section">
    <div class="pet-photo-wrapper">
      <div class="pet-photo" :class="{ 'pet-photo--placeholder': !photoObjectUrl }">
        <img v-if="photoObjectUrl" :src="photoObjectUrl" :alt="pet.name" class="pet-photo__img" />
        <PhCat v-else :size="48" class="pet-photo__placeholder-icon" />
      </div>
      <button
        class="pet-photo__camera-btn tap-target"
        @click="fileInputRef?.click()"
        :disabled="photoUploading"
        :aria-label="$t('pets.changePhoto')"
      >
        <PhCamera :size="16" />
      </button>
    </div>
    <span v-if="photoUploading" class="pet-photo__upload-status">
      {{ $t('pets.photoUploading') }}
    </span>
  </div>
  <input
    ref="fileInputRef"
    type="file"
    accept="image/*"
    class="pet-photo__input"
    @change="handlePhotoUpload"
  />

  <!-- ═══ Header ═══ -->
  <div class="detail-header">
    <button class="back-btn tap-target" @click="router.back()" :aria-label="$t('common.back')">
      <PhArrowLeft :size="24" weight="bold" />
    </button>
    <div class="detail-header__info">
      <span class="detail-header__emoji">{{ speciesEmoji(pet.species) }}</span>
      <h1 class="detail-header__name">{{ pet.name }}</h1>
      <span v-if="pet.archived" class="archived-badge">{{ $t('pets.archivedBadge') }}</span>
    </div>
    <button class="edit-btn tap-target" @click="emit('edit')" :aria-label="$t('common.edit')">
      <PhPencilSimple :size="20" weight="bold" />
    </button>
  </div>
</template>

<style scoped>
/* ── Header ── */
.detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.back-btn,
.edit-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
}

.back-btn:hover,
.edit-btn:hover {
  color: var(--ink);
  background: var(--chip);
}

.detail-header__info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.detail-header__emoji {
  font-size: var(--text-xl);
}

.archived-badge {
  font-size: var(--text-xs);
  padding: var(--space-0-5) var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--chip);
  color: var(--sub);
}

.detail-header__name {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── Pet Photo ── */
.pet-photo-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: var(--space-4);
}

.pet-photo-wrapper {
  position: relative;
}

.pet-photo {
  width: 112px;
  height: 112px;
  border-radius: 50%;
  overflow: hidden;
  border: 2px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
}

.pet-photo--placeholder {
  background: var(--chip);
}

.pet-photo__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pet-photo__placeholder-icon {
  color: var(--sub);
}

.pet-photo__camera-btn {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
  border: 2px solid var(--card);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: var(--shadow-card);
  transition: transform var(--transition-fast);
}

.pet-photo__camera-btn:active {
  transform: scale(0.92);
}

.pet-photo__camera-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.pet-photo__input {
  display: none;
}

.pet-photo__upload-status {
  font-size: var(--text-xs);
  color: var(--sub);
  margin-top: var(--space-1);
}
</style>
