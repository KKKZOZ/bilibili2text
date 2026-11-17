<script setup>
  import { computed } from 'vue'
  import { Download, Eye, LoaderCircle, Sparkles } from 'lucide-vue-next'
  import ExportMenu from './ExportMenu.vue'

  const props = defineProps({
    item: { type: Object, required: true },
    primaryLoading: Boolean,
    canConvert: Boolean,
    fancyLoading: Boolean,
    txtLoading: Boolean,
    pdfLoading: Boolean,
    pngOpen: Boolean,
    pngLoading: Boolean,
    desktopPngLoading: Boolean,
    mobilePngLoading: Boolean,
    renderedSummary: Boolean
  })

  const emit = defineEmits([
    'primary',
    'fancy',
    'convert',
    'togglePng',
    'png',
    'preview'
  ])

  // Reports and timelines open in a new tab; everything else downloads.
  const primaryIsPreview = computed(() =>
    ['summary_fancy_html', 'summary_timeline'].includes(props.item.kind)
  )

  const exportOptions = computed(() => {
    const png = [
      {
        key: 'png-desktop',
        label: 'PNG · 桌面版',
        loading: props.desktopPngLoading
      },
      {
        key: 'png-mobile',
        label: 'PNG · 手机版',
        loading: props.mobilePngLoading
      }
    ]
    if (props.item.kind === 'summary_fancy_html') return png
    if (!props.canConvert) return []
    return [
      ...(props.renderedSummary
        ? []
        : [{ key: 'txt', label: 'TXT', loading: props.txtLoading }]),
      { key: 'pdf', label: 'PDF', loading: props.pdfLoading },
      ...png
    ]
  })

  const onExportSelect = (key) => {
    if (key === 'png-desktop') emit('png', 'desktop')
    else if (key === 'png-mobile') emit('png', 'mobile')
    else emit('convert', key)
  }
</script>

<template>
  <div class="artifact-actions">
    <button
      v-if="item.kind === 'rag_answer'"
      type="button"
      :disabled="fancyLoading"
      @click="emit('fancy')"
    >
      <LoaderCircle v-if="fancyLoading" :size="14" class="spin" />
      <Sparkles v-else :size="14" aria-hidden="true" />
      <span>{{ fancyLoading ? '生成中...' : '生成阅读报告' }}</span>
    </button>

    <button
      v-if="canConvert && renderedSummary"
      type="button"
      :aria-label="`预览 ${item.displayName}`"
      @click="emit('preview')"
    >
      <Eye :size="14" aria-hidden="true" /><span>预览</span>
    </button>

    <ExportMenu
      v-if="exportOptions.length"
      :open="pngOpen"
      :options="exportOptions"
      @toggle="emit('togglePng')"
      @select="onExportSelect"
    />

    <button
      type="button"
      class="primary-action"
      :disabled="primaryLoading"
      :aria-label="`${primaryIsPreview ? '预览' : '下载'} ${item.displayName}`"
      @click="emit('primary')"
    >
      <LoaderCircle v-if="primaryLoading" :size="14" class="spin" />
      <Eye v-else-if="primaryIsPreview" :size="14" aria-hidden="true" />
      <Download v-else :size="14" aria-hidden="true" />
      <span>{{ primaryIsPreview ? '预览' : '下载' }}</span>
    </button>
  </div>
</template>

<style scoped>
  .artifact-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 6px;
  }
  .artifact-actions > button {
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
  .artifact-actions > button:hover:not(:disabled) {
    border-color: var(--brand);
    color: var(--brand-strong);
  }
  .artifact-actions > button:focus-visible {
    outline: 3px solid var(--focus-ring);
    outline-offset: 1px;
  }
  .artifact-actions > button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
  .artifact-actions > .primary-action {
    border-color: var(--brand-line);
    background: var(--brand-soft);
    color: var(--brand-strong);
  }

  @media (max-width: 640px) {
    .artifact-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      width: 100%;
      gap: 8px;
    }

    .artifact-actions > button {
      width: 100%;
    }
  }
</style>
