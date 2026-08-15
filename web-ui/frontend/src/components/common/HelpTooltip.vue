<script setup>
  import { CircleHelp } from 'lucide-vue-next'

  defineProps({
    id: { type: String, required: true },
    label: { type: String, required: true }
  })
</script>

<template>
  <span class="help-tooltip-root">
    <button
      type="button"
      class="help-tooltip-trigger"
      :aria-label="label"
      :aria-describedby="id"
    >
      <CircleHelp :size="15" aria-hidden="true" />
    </button>
    <span :id="id" class="help-tooltip-content" role="tooltip">
      <slot />
    </span>
  </span>
</template>

<style scoped>
  .help-tooltip-root {
    position: relative;
    display: inline-flex;
  }

  .help-tooltip-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: #64748b;
    cursor: help;
  }

  .help-tooltip-trigger:focus-visible {
    outline: 0;
    box-shadow: 0 0 0 3px rgba(15, 143, 131, 0.14);
  }

  .help-tooltip-content {
    position: absolute;
    z-index: 40;
    bottom: calc(100% + 8px);
    left: 50%;
    width: min(360px, calc(100vw - 48px));
    padding: 10px 12px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #fff;
    color: #334155;
    font-size: 0.82rem;
    font-weight: 500;
    line-height: 1.55;
    opacity: 0;
    pointer-events: none;
    transform: translate(-50%, 4px);
    transition: 0.16s ease;
  }

  .help-tooltip-root:hover .help-tooltip-content,
  .help-tooltip-root:focus-within .help-tooltip-content {
    opacity: 1;
    transform: translate(-50%, 0);
  }

  @media (max-width: 640px) {
    .help-tooltip-content {
      right: -112px;
      left: auto;
      width: min(292px, calc(100vw - 48px));
      transform: translateY(4px);
    }

    .help-tooltip-root:hover .help-tooltip-content,
    .help-tooltip-root:focus-within .help-tooltip-content {
      transform: translateY(0);
    }
  }
</style>
