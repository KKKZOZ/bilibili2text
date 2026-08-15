<script setup>
  import {
    Braces,
    Eye,
    File,
    FileText,
    LoaderCircle,
    Music,
    Type
  } from 'lucide-vue-next'
  import PngExportMenu from './PngExportMenu.vue'

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
  const normalizedType = () => String(props.item.fileType || '').toLowerCase()
  const primaryLabel = () => {
    if (props.item.kind === 'summary_fancy_html') return 'HTML Preview'
    if (props.item.kind === 'summary_timeline') return 'TXT Preview'
    return (
      { markdown: 'Markdown', json: 'JSON', audio: '音频', 音频: '音频' }[
        normalizedType()
      ] || props.item.fileType
    )
  }
  const primaryIcon = () => {
    if (['summary_fancy_html', 'summary_timeline'].includes(props.item.kind))
      return Eye
    return (
      { markdown: FileText, json: Braces, audio: Music, 音频: Music }[
        normalizedType()
      ] || File
    )
  }
</script>

<template>
  <div class="artifact-actions">
    <button type="button" :disabled="primaryLoading" @click="emit('primary')">
      <LoaderCircle v-if="primaryLoading" :size="14" class="spin" />
      <component :is="primaryIcon()" v-else :size="14" />
      <span>{{ primaryLabel() }}</span>
    </button>

    <template v-if="item.kind === 'summary_fancy_html'">
      <PngExportMenu
        :open="pngOpen"
        :loading="pngLoading"
        :desktop-loading="desktopPngLoading"
        :mobile-loading="mobilePngLoading"
        @toggle="emit('togglePng')"
        @export="emit('png', $event)"
      />
    </template>

    <template v-else-if="canConvert">
      <button
        v-if="item.kind === 'summary' || item.kind === 'rag_answer'"
        type="button"
        :disabled="fancyLoading"
        @click="emit('fancy')"
      >
        <LoaderCircle v-if="fancyLoading" :size="14" class="spin" />
        <FileText v-else :size="14" /><span>Fancy HTML</span>
      </button>
      <button
        v-if="!renderedSummary"
        type="button"
        :disabled="txtLoading"
        @click="emit('convert', 'txt')"
      >
        <LoaderCircle v-if="txtLoading" :size="14" class="spin" />
        <Type v-else :size="14" /><span>TXT</span>
      </button>
      <button
        type="button"
        :disabled="pdfLoading"
        @click="emit('convert', 'pdf')"
      >
        <LoaderCircle v-if="pdfLoading" :size="14" class="spin" />
        <FileText v-else :size="14" /><span>PDF</span>
      </button>
      <PngExportMenu
        :open="pngOpen"
        :loading="pngLoading"
        :desktop-loading="desktopPngLoading"
        :mobile-loading="mobilePngLoading"
        @toggle="emit('togglePng')"
        @export="emit('png', $event)"
      />
      <button v-if="renderedSummary" type="button" @click="emit('preview')">
        <Eye :size="14" /><span>HTML Preview</span>
      </button>
    </template>
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
    border-radius: 7px;
    background: rgba(255, 255, 255, 0.9);
    color: var(--text-soft);
    font-size: 0.78rem;
    font-weight: 700;
    cursor: pointer;
  }
  .artifact-actions > button:hover:not(:disabled) {
    border-color: var(--brand);
    color: var(--brand-strong);
  }
  .artifact-actions > button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
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
