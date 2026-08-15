<script setup>
  import {
    ChevronDown,
    Image as ImageIcon,
    LoaderCircle
  } from 'lucide-vue-next'
  import { ref } from 'vue'
  import { useClickOutside } from '../../composables/useClickOutside'

  const props = defineProps({
    open: Boolean,
    loading: Boolean,
    desktopLoading: Boolean,
    mobileLoading: Boolean
  })
  const emit = defineEmits(['toggle', 'export'])
  const root = ref(null)

  useClickOutside(root, () => {
    if (props.open) emit('toggle')
  })
</script>

<template>
  <div ref="root" class="png-export-menu" :class="{ open }">
    <button
      type="button"
      :disabled="loading"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <LoaderCircle v-if="loading" :size="14" class="spin" />
      <template v-else>
        <ImageIcon :size="14" /><span>PNG</span
        ><ChevronDown :size="14" :class="{ rotated: open }" />
      </template>
    </button>
    <div v-if="open" class="png-options" role="menu">
      <button
        type="button"
        :disabled="desktopLoading"
        @click="emit('export', 'desktop')"
      >
        <LoaderCircle v-if="desktopLoading" :size="14" class="spin" /><span
          >Desktop</span
        >
      </button>
      <button
        type="button"
        :disabled="mobileLoading"
        @click="emit('export', 'mobile')"
      >
        <LoaderCircle v-if="mobileLoading" :size="14" class="spin" /><span
          >Mobile</span
        >
      </button>
    </div>
  </div>
</template>

<style scoped>
  .png-export-menu {
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
    border-radius: 7px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text-soft);
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
  }
  button:hover:not(:disabled) {
    border-color: var(--brand);
    color: var(--brand-strong);
  }
  button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
  .rotated {
    transform: rotate(180deg);
  }
  .png-options {
    position: absolute;
    z-index: 30;
    top: calc(100% + 5px);
    right: 0;
    display: grid;
    min-width: 120px;
    padding: 5px;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
    box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
  }
  .png-options button {
    justify-content: flex-start;
    width: 100%;
    border: 0;
  }

  @media (max-width: 640px) {
    .png-export-menu,
    .png-export-menu > button {
      width: 100%;
    }

    .png-options {
      right: 0;
      left: 0;
    }
  }
</style>
