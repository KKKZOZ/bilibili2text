<script setup>
  import { RotateCcw, SlidersHorizontal } from 'lucide-vue-next'
  import MultiSelectPopover from '../common/MultiSelectPopover.vue'

  defineProps({
    platforms: { type: Array, default: () => [] },
    categories: { type: Array, default: () => [] },
    authors: { type: Array, default: () => [] },
    platformOptions: { type: Array, default: () => [] },
    categoryOptions: { type: Array, default: () => [] },
    authorOptions: { type: Array, default: () => [] },
    platformLabel: { type: String, required: true },
    categoryLabel: { type: String, required: true },
    authorLabel: { type: String, required: true },
    loading: Boolean
  })

  const emit = defineEmits([
    'update:platforms',
    'update:categories',
    'update:authors',
    'reset'
  ])
</script>

<template>
  <div class="history-filter-bar">
    <div class="history-filter-heading">
      <SlidersHorizontal :size="15" /><span>筛选</span>
    </div>
    <MultiSelectPopover
      label="平台"
      :trigger-label="platformLabel"
      :model-value="platforms"
      :options="platformOptions"
      :disabled="loading"
      empty-text="暂无平台"
      @update:model-value="emit('update:platforms', $event)"
    />
    <MultiSelectPopover
      label="分区"
      :trigger-label="categoryLabel"
      :model-value="categories"
      :options="categoryOptions"
      :disabled="loading"
      empty-text="暂无分区"
      @update:model-value="emit('update:categories', $event)"
    />
    <MultiSelectPopover
      label="UP 主"
      :trigger-label="authorLabel"
      :model-value="authors"
      :options="authorOptions"
      :disabled="loading"
      empty-text="暂无 UP 主"
      @update:model-value="emit('update:authors', $event)"
    />
    <button
      type="button"
      class="history-filter-reset"
      :disabled="platforms.length + categories.length + authors.length === 0"
      @click="emit('reset')"
    >
      <RotateCcw :size="14" /><span>重置</span>
    </button>
  </div>
</template>

<style scoped>
  .history-filter-bar {
    display: grid;
    grid-template-columns:
      auto minmax(140px, 0.8fr) minmax(170px, 1fr) minmax(190px, 1.2fr)
      auto;
    align-items: end;
    gap: 12px;
    padding: 14px 16px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
    box-shadow: var(--panel-shadow);
  }

  .history-filter-heading {
    display: inline-flex;
    align-items: center;
    align-self: center;
    gap: 6px;
    color: #475569;
    font-size: 0.82rem;
    font-weight: 700;
    white-space: nowrap;
  }

  .history-filter-heading svg {
    color: #0f766e;
  }

  .history-filter-reset {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    height: 36px;
    padding: 0 11px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #475569;
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
  }

  .history-filter-reset:disabled {
    cursor: default;
    opacity: 0.45;
  }

  @media (max-width: 860px) {
    .history-filter-bar {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .history-filter-heading,
    .history-filter-reset {
      grid-column: 1 / -1;
    }
  }

  @media (max-width: 560px) {
    .history-filter-bar {
      grid-template-columns: 1fr;
    }
  }
</style>
