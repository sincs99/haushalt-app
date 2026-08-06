<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string
  label?: string
  placeholder?: string
  type?: string
  id?: string
  disabled?: boolean
  error?: string
  autocomplete?: string
}>(), {
  type: 'text',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const inputId = computed(() => props.id ?? (props.label ? `input-${props.label.toLowerCase().replace(/\s+/g, '-')}` : undefined))
</script>

<template>
  <div class="base-input">
    <label v-if="label" :for="inputId" class="base-input__label">
      {{ label }}
    </label>
    <input
      :id="inputId"
      class="base-input__field"
      :class="{ 'base-input__field--error': !!error }"
      :type="type"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :autocomplete="autocomplete"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <p v-if="error" class="base-input__error">
      {{ error }}
    </p>
  </div>
</template>

<style scoped>
.base-input {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.base-input__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
}

.base-input__field {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-family: var(--font-family);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  line-height: var(--line-height-normal);
  color: var(--color-text);
  background-color: var(--color-surface);
  transition: border-color var(--transition-fast),
              box-shadow var(--transition-fast);
}

.base-input__field::placeholder {
  color: var(--color-text-muted);
}

.base-input__field:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.base-input__field--error {
  border-color: var(--color-danger);
}

.base-input__field--error:focus {
  box-shadow: 0 0 0 3px var(--color-danger-light);
}

.base-input__field:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background-color: var(--color-neutral-100);
}

.base-input__error {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}
</style>
