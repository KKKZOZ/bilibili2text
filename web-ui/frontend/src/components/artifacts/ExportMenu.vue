<script setup>
  import { ChevronDown, LoaderCircle, Share } from 'lucide-vue-next'
  import { ref } from 'vue'
  import { useClickOutside } from '../../composables/useClickOutside'

  const props = defineProps({
    open: Boolean,
    // [{ key, label, loading }]
    options: { type: Array, default: () => [] }
  })
  const emit = defineEmits(['toggle', 'select'])
  const root = ref(null)
  const trigger = ref(null)

  useClickOutside(root, () => {
    if (props.open) emit('toggle')
  })

  const onKeydown = (event) => {
    if (event.key === 'Escape' && props.open) {
      event.stopPropagation()
      emit('toggle')
      trigger.value?.focus()
    }
  }
</script>

<template>
  <div ref="root" class="export-menu" :class="{ open }" @keydown="onKeydown">
    <button
      ref="trigger"
      type="button"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <LoaderCircle
        v-if="options.some((option) => option.loading)"
        :size="14"
        class="spin"
      />
      <Share v-else :size="14" aria-hidden="true" />
      <span>导出</span>
      <ChevronDown :size="14" :class="{ rotated: open }" aria-hidden="true" />
    </button>
    <div v-if="open" class="export-options" role="menu">
      <button
        v-for="option in options"
        :key="option.key"
        type="button"
        role="menuitem"
        :disabled="option.loading"
        @click="emit('select', option.key)"
      >
        <LoaderCircle v-if="option.loading" :size="14" class="spin" />
        <span>{{ option.label }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
  .export-menu {
    position: relative;
  }
  button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    min-height: 34px;
    padding: 0 10px;
    border: 1px solid var(--line);
    border-radius: var(--radius-lg);
    background: var(--panel-bg);
    color: var(--text-soft);
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
  }
  button:hover:not(:disabled) {
    border-color: var(--brand);
    color: var(--brand-strong);
  }
  button:focus-visible {
    outline: 3px solid var(--focus-ring);
    outline-offset: 1px;
  }
  button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
  .rotated {
    transform: rotate(180deg);
  }
  .export-options {
    position: absolute;
    z-index: 30;
    top: calc(100% + 5px);
    right: 0;
    display: grid;
    min-width: 148px;
    padding: 5px;
    border: 1px solid var(--line);
    border-radius: var(--radius-lg);
    background: var(--panel-bg);
    box-shadow: var(--shadow-pop);
  }
  .export-options button {
    justify-content: flex-start;
    width: 100%;
    border: 0;
  }
  .export-options button:hover:not(:disabled) {
    background: var(--surface-muted);
  }

  @media (max-width: 640px) {
    .export-menu,
    .export-menu > button {
      width: 100%;
    }

    .export-options {
      right: 0;
      left: 0;
    }
  }
</style>
