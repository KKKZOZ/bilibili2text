<script setup>
  import { computed } from 'vue'
  import { AlertCircle, CheckCircle2, Info } from 'lucide-vue-next'

  const props = defineProps({
    kind: {
      type: String,
      default: 'error',
      validator: (value) =>
        ['error', 'warning', 'success', 'info'].includes(value)
    },
    compact: Boolean
  })

  const icon = computed(() => {
    if (props.kind === 'success') return CheckCircle2
    if (props.kind === 'info') return Info
    return AlertCircle
  })
</script>

<template>
  <p class="inline-notice" :class="[`inline-notice-${kind}`, { compact }]">
    <component :is="icon" :size="compact ? 14 : 16" aria-hidden="true" />
    <span><slot /></span>
    <slot name="action"></slot>
  </p>
</template>

<style scoped>
  .inline-notice {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    margin: 12px 0 0;
    font-size: 0.9rem;
    line-height: 1.5;
  }

  .inline-notice svg {
    flex: 0 0 auto;
    margin-top: 2px;
  }

  .inline-notice-error {
    color: var(--danger);
  }

  .inline-notice-warning {
    color: #92400e;
  }

  .inline-notice-success {
    color: #047857;
  }

  .inline-notice-info {
    color: var(--text-muted);
  }

  .compact {
    margin-top: 6px;
    font-size: 0.82rem;
  }
</style>
