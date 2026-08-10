<script setup lang="ts">
import { computed } from 'vue'

defineOptions({ inheritAttrs: false })

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
      v-bind="$attrs"
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
  color: var(--ink);
}

.base-input__field {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-family: var(--font-family);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  line-height: var(--line-height-normal);
  color: var(--ink);
  background-color: var(--card);
  transition: border-color var(--transition-fast),
              box-shadow var(--transition-fast);
}

.base-input__field::placeholder {
  color: var(--sub);
}

.base-input__field:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

.base-input__field--error {
  border-color: var(--color-danger);
}

.base-input__field--error:focus {
  box-shadow: 0 0 0 3px var(--acc-soft);
}

.base-input__field:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background-color: var(--chip);
}

.base-input__error {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}
</style>
