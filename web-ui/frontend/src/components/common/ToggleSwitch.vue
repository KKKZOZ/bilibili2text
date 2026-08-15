<script setup>
  defineProps({
    modelValue: Boolean,
    id: {
      type: String,
      required: true
    },
    label: {
      type: String,
      required: true
    },
    compact: Boolean,
    disabled: Boolean
  })

  const emit = defineEmits(['update:modelValue'])
</script>

<template>
  <label class="toggle-switch" :class="{ compact }" :for="id">
    <input
      :id="id"
      type="checkbox"
      :checked="modelValue"
      :disabled="disabled"
      @change="emit('update:modelValue', $event.target.checked)"
    />
    <span class="toggle-track"><span class="toggle-thumb"></span></span>
    <span class="toggle-label">{{ label }}</span>
  </label>
</template>

<style scoped>
  .toggle-switch {
    display: inline-flex;
    align-items: center;
    gap: 12px;
    min-height: 26px;
    cursor: pointer;
    user-select: none;
  }

  .toggle-switch input {
    position: absolute;
    width: 0;
    height: 0;
    opacity: 0;
  }

  .toggle-track {
    flex: 0 0 auto;
    width: 46px;
    height: 26px;
    padding: 2px;
    border: 1px solid #cbd5e1;
    border-radius: 999px;
    background: #e2e8f0;
    transition:
      background-color 0.25s ease,
      border-color 0.25s ease;
  }

  .toggle-thumb {
    display: block;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.15);
    transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  }

  input:checked + .toggle-track {
    border-color: #14b8a6;
    background: linear-gradient(135deg, #14b8a6, #0ea5e9);
  }

  input:checked + .toggle-track .toggle-thumb {
    transform: translateX(20px);
  }

  input:focus-visible + .toggle-track {
    box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.2);
  }

  input:disabled ~ span {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .toggle-label {
    color: var(--text-soft);
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1.25;
  }

  .compact {
    gap: 10px;
  }

  .compact .toggle-label {
    font-size: 0.88rem;
  }
</style>
