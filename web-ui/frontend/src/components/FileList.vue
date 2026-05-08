<script setup>
  import { computed, ref } from 'vue'
  import {
    AlertCircle,
    Braces,
    File,
    FileText,
    Image as ImageIcon,
    LoaderCircle,
    Music,
    Trash2,
    Type
  } from 'lucide-vue-next'
  import { useConversion } from '../composables/useConversion'
  import { resolveFileType, buildArtifactDisplayName } from '../utils/fileUtils'

  const props = defineProps({
    items: {
      type: Array,
      required: true
    },
    summaryPresets: {
      type: Array,
      default: () => []
    },
    summaryDefaultPreset: {
      type: String,
      default: ''
    },
    selectedSummaryPreset: {
      type: String,
      default: ''
    },
    summaryProfiles: {
      type: Array,
      default: () => []
    },
    selectedSummaryProfile: {
      type: String,
      default: ''
    },
    bvid: {
      type: String,
      default: ''
    },
    title: {
      type: String,
      default: '基本文件'
    },
    historyRunId: {
      type: String,
      default: ''
    },
    filterKinds: {
      type: Array,
      default: () => [
        'markdown',
        'summary',
        'summary_no_table',
        'summary_fancy_html',
        'summary_table_md',
        'summary_table_pdf'
      ]
    },
    allowDelete: {
      type: Boolean,
      default: true
    },
    requiresApiKey: {
      type: Boolean,
      default: false
    }
  })

  const emit = defineEmits(['artifactDeleted', 'artifactGenerated'])
  const LOCAL_API_KEY_KEY = 'b2t.public-api-key'
  const LOCAL_DEEPSEEK_API_KEY_KEY = 'b2t.public-deepseek-api-key'

  const { conversionError, convertAndDownload, isConverting, download } =
    useConversion()
  const noTableConverting = ref(new Set())
  const fancyGenerating = ref(new Set())
  const deleteError = ref('')
  const deletingKeys = ref(new Set())
  const deleteConfirmItem = ref(null)
  const generatedItems = ref([])

  const formatIconMap = {
    markdown: FileText,
    txt: Type,
    pdf: FileText,
    html: FileText,
    png: ImageIcon,
    json: Braces,
    音频: Music,
    audio: Music
  }

  const normalizeFormatKey = (value) => (value || '').trim().toLowerCase()

  const formatLabelMap = {
    markdown: 'Markdown',
    txt: 'TXT',
    pdf: 'PDF',
    html: 'HTML',
    png: 'PNG',
    json: 'JSON',
    音频: '音频',
    audio: '音频'
  }

  const getFormatIcon = (format) =>
    formatIconMap[normalizeFormatKey(format)] || File

  const getFormatLabel = (format) =>
    formatLabelMap[normalizeFormatKey(format)] || format || '文件'

  const readLocalStorage = (key) => {
    try {
      return (window.localStorage.getItem(key) || '').trim()
    } catch {
      return ''
    }
  }

  const resolveSummaryPresetLabel = (presetName) => {
    let effectiveName = (presetName || '').trim()
    if (!effectiveName || effectiveName === 'default') {
      effectiveName =
        props.summaryDefaultPreset || props.selectedSummaryPreset || 'default'
    }
    const matched = props.summaryPresets.find(
      (item) => item.name === effectiveName
    )
    if (matched && typeof matched.label === 'string' && matched.label.trim()) {
      return matched.label.trim()
    }
    return effectiveName
  }

  const isSummaryKind = (kind) =>
    kind === 'summary' ||
    kind === 'summary_text' ||
    kind === 'summary_no_table' ||
    kind === 'summary_png' ||
    kind === 'summary_no_table_png' ||
    kind === 'summary_fancy_html' ||
    kind === 'summary_table_md' ||
    kind === 'summary_table_png' ||
    kind === 'summary_table_pdf'

  const isSummaryDerivedKind = (kind) =>
    kind === 'summary_no_table' ||
    kind === 'summary_png' ||
    kind === 'summary_no_table_png' ||
    kind === 'summary_fancy_html' ||
    kind === 'summary_table_md' ||
    kind === 'summary_table_png' ||
    kind === 'summary_table_pdf'

  const isHiddenDerivedPngKind = (kind) =>
    kind === 'summary_png' ||
    kind === 'summary_no_table_png' ||
    kind === 'summary_table_png'

  const resolveSummaryProfileLabel = (profileName) => {
    const effectiveName = (profileName || '').trim()
    if (!effectiveName) {
      return ''
    }
    const matched = props.summaryProfiles.find(
      (item) => item.name === effectiveName
    )
    if (matched && typeof matched.name === 'string' && matched.name.trim()) {
      return matched.name.trim()
    }
    return effectiveName
  }

  const resolveSummaryFamilyKey = (item, kind) => {
    if (
      !item ||
      typeof item.filename !== 'string' ||
      item.filename.trim() === ''
    ) {
      return ''
    }
    const stem = item.filename.replace(/\.[^.]*$/, '')
    if (
      kind === 'summary' ||
      kind === 'summary_no_table' ||
      kind === 'summary_png' ||
      kind === 'summary_no_table_png' ||
      kind === 'summary_text'
    ) {
      return stem.replace(/_no_table$/i, '')
    }
    if (
      kind === 'summary_fancy_html' ||
      kind === 'summary_table_md' ||
      kind === 'summary_table_png' ||
      kind === 'summary_table_pdf'
    ) {
      return stem.replace(/_fancy$/i, '').replace(/_table$/i, '')
    }
    return ''
  }

  const displayItems = computed(() => {
    const formatPriority = {
      Markdown: 0,
      TXT: 1,
      PDF: 2,
      HTML: 3,
      PNG: 4,
      JSON: 5,
      音频: 6
    }
    const kindBaseOrder = {
      markdown: 100,
      summary: 200,
      summary_no_table: 210,
      summary_png: 211,
      summary_no_table_png: 212,
      summary_fancy_html: 220,
      summary_table_md: 230,
      summary_table_png: 231,
      summary_table_pdf: 231,
      text: 300,
      summary_text: 310,
      json: 400,
      audio: 500,
      rag_answer: 50
    }

    const toDisplayItem = (item, index, overrides = {}) => {
      const kind = overrides.kind || item.kind
      const fileType =
        overrides.fileType || resolveFileType(item.filename, kind)
      const isDerivedFromSummary = isSummaryDerivedKind(kind)
      const displayName =
        overrides.displayName ||
        buildArtifactDisplayName(
          {
            ...item,
            kind
          },
          { bvid: props.bvid }
        )

      return {
        ...item,
        ...overrides,
        kind,
        displayName,
        fileType,
        formatPriority: formatPriority[fileType] ?? 99,
        presetLabel:
          kind === 'summary' ||
          kind === 'summary_text' ||
          kind === 'summary_no_table' ||
          kind === 'summary_png' ||
          kind === 'summary_no_table_png' ||
          kind === 'summary_fancy_html' ||
          kind === 'summary_table_md' ||
          kind === 'summary_table_png'
            ? resolveSummaryPresetLabel(item.presetName || '')
            : '',
        modelProfileLabel: isSummaryKind(kind)
          ? resolveSummaryProfileLabel(item.summaryProfile || '')
          : '',
        downloadId: item.url.split('/').pop(),
        summarySignature:
          overrides.summarySignature ||
          `${(item.presetName || '').trim()}::${(item.summaryProfile || '').trim()}`,
        summaryFamilyKey:
          overrides.summaryFamilyKey || resolveSummaryFamilyKey(item, kind),
        summaryRowId:
          overrides.summaryRowId ||
          (kind === 'summary'
            ? extractDownloadId(item.url) || `summary-${index}`
            : ''),
        parentSummaryRowId: overrides.parentSummaryRowId || '',
        order:
          overrides.order ??
          (kindBaseOrder[kind] !== undefined
            ? kindBaseOrder[kind] + index / 100
            : 900 + index),
        isWideLayout:
          kind === 'markdown' ||
          kind === 'summary_no_table' ||
          kind === 'summary_png' ||
          kind === 'summary_no_table_png' ||
          kind === 'summary_fancy_html',
        primaryTargetFormat: kind === 'summary_no_table' ? 'md_no_table' : '',
        noTableBadge: kind === 'summary_no_table',
        derivedFromSummary: isDerivedFromSummary
      }
    }

    const rows = []
    const sourceItems = [...props.items, ...generatedItems.value]
    const filteredItems = sourceItems.filter(
      (item) =>
        !isHiddenDerivedPngKind(item.kind) &&
        props.filterKinds.includes(item.kind)
    )
    const summaryRowsByFamily = new Map()
    const summaryRowsBySignature = new Map()

    // Phase 1: build summary roots and synthetic summary_no_table rows.
    let summaryIndex = 0
    filteredItems.forEach((item, index) => {
      if (item.kind === 'summary') {
        const currentSummaryIndex = summaryIndex++
        const summaryId = extractDownloadId(item.url) || `summary-${index}`
        const signature = `${(item.presetName || '').trim()}::${(item.summaryProfile || '').trim()}`
        const familyKey = resolveSummaryFamilyKey(item, 'summary')
        const summaryRow = toDisplayItem(item, index, {
          summaryRowId: summaryId,
          summarySignature: signature,
          summaryFamilyKey: familyKey,
          order: kindBaseOrder['summary'] + currentSummaryIndex
        })
        rows.push(summaryRow)

        if (familyKey) {
          summaryRowsByFamily.set(`${familyKey}::${signature}`, summaryRow)
        }
        const bucket = summaryRowsBySignature.get(signature) || []
        bucket.push(summaryRow)
        summaryRowsBySignature.set(signature, bucket)

        if (props.filterKinds.includes('summary_no_table')) {
          rows.push(
            toDisplayItem(item, index, {
              key: `${item.key || item.url || item.filename}-summary-no-table`,
              kind: 'summary_no_table',
              displayName: `${buildArtifactDisplayName(item, { bvid: props.bvid })}_无表格`,
              fileType: 'Markdown',
              order: summaryRow.order + 0.1,
              parentSummaryRowId: summaryId,
              summarySignature: signature,
              summaryFamilyKey: familyKey
            })
          )
        }
      }
    })

    // Phase 2: build non-summary rows and bind derived artifacts to parent summary.
    filteredItems.forEach((item, index) => {
      if (item.kind === 'summary') {
        return
      }

      if (
        item.kind === 'summary_fancy_html' ||
        item.kind === 'summary_table_md' ||
        item.kind === 'summary_table_png' ||
        item.kind === 'summary_table_pdf'
      ) {
        const signature = `${(item.presetName || '').trim()}::${(item.summaryProfile || '').trim()}`
        const familyKey = resolveSummaryFamilyKey(item, item.kind)
        const compositeKey = familyKey ? `${familyKey}::${signature}` : ''
        let parentSummary = compositeKey
          ? summaryRowsByFamily.get(compositeKey) || null
          : null
        if (!parentSummary) {
          const sameSignature = summaryRowsBySignature.get(signature) || []
          parentSummary =
            sameSignature.length > 0
              ? sameSignature[sameSignature.length - 1]
              : null
        }
        const derivedOffset =
          item.kind === 'summary_fancy_html'
            ? 0.15
            : item.kind === 'summary_table_md'
              ? 0.2
              : item.kind === 'summary_table_png'
                ? 0.21
                : item.kind === 'summary_table_pdf'
                  ? 0.25
                  : 0.18
        rows.push(
          toDisplayItem(item, index, {
            parentSummaryRowId: parentSummary?.summaryRowId || '',
            summarySignature: signature,
            summaryFamilyKey: familyKey,
            order: parentSummary
              ? parentSummary.order + derivedOffset
              : undefined
          })
        )
        return
      }

      rows.push(toDisplayItem(item, index))
    })

    const sortedRows = rows.sort((a, b) => {
      if (a.order === b.order && a.formatPriority !== b.formatPriority) {
        return a.formatPriority - b.formatPriority
      }
      return a.order - b.order
    })

    const summaryNameById = new Map(
      sortedRows
        .filter((item) => item.kind === 'summary' && item.summaryRowId)
        .map((item) => [item.summaryRowId, item.displayName])
    )

    return sortedRows.map((item) => ({
      ...item,
      parentSummaryName: item.parentSummaryRowId
        ? summaryNameById.get(item.parentSummaryRowId) || ''
        : ''
    }))
  })

  const canConvert = (kind) => {
    return (
      kind === 'markdown' ||
      kind === 'summary' ||
      kind === 'summary_no_table' ||
      kind === 'summary_table_md' ||
      kind === 'rag_answer'
    )
  }

  const isPrimaryConverting = (item) => {
    if (!item.primaryTargetFormat) {
      return false
    }
    return isConverting(item.downloadId, item.primaryTargetFormat)
  }

  const handlePrimaryAction = (item) => {
    if (item.primaryTargetFormat) {
      convertAndDownload(
        item.downloadId,
        item.filename,
        item.primaryTargetFormat
      )
      return
    }
    download(item.url, item.filename)
  }

  const noTableConvertKey = (downloadId, targetFormat) =>
    `${downloadId}-summary-no-table-${targetFormat}`

  const fancyGenerateKey = (downloadId) => `${downloadId}-summary-fancy-html`

  const isNoTableConverting = (item, targetFormat) =>
    noTableConverting.value.has(
      noTableConvertKey(item.downloadId, targetFormat)
    )

  const requestConvert = async (
    downloadId,
    targetFormat,
    extraPayload = {}
  ) => {
    const resp = await fetch('/api/convert', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        download_id: downloadId,
        target_format: targetFormat,
        ...extraPayload
      })
    })
    const data = await resp.json()
    if (!resp.ok) {
      throw new Error(data.detail || '转换失败')
    }
    return data
  }

  const extractDownloadId = (downloadUrl) => {
    if (typeof downloadUrl !== 'string') {
      return ''
    }
    return downloadUrl.split('/').pop() || ''
  }

  const isFancyGenerating = (item) =>
    (item.kind === 'summary' || item.kind === 'rag_answer') &&
    fancyGenerating.value.has(fancyGenerateKey(item.downloadId))

  const addGeneratedArtifact = (artifact) => {
    if (!artifact?.download_url || !artifact?.filename || !artifact?.kind) {
      return
    }
    generatedItems.value = [
      ...generatedItems.value.filter(
        (item) => item.url !== artifact.download_url
      ),
      {
        key: `${artifact.download_url}-${artifact.filename}-generated`,
        kind: artifact.kind,
        url: artifact.download_url,
        filename: artifact.filename,
        presetName: artifact.summary_preset || '',
        summaryProfile: artifact.summary_profile || ''
      }
    ]
  }

  const convertNoTableAndDownload = async (item, targetFormat) => {
    const key = noTableConvertKey(item.downloadId, targetFormat)
    if (noTableConverting.value.has(key)) {
      return
    }

    noTableConverting.value.add(key)
    conversionError.value = ''
    try {
      const noTableData = await requestConvert(item.downloadId, 'md_no_table')
      if (targetFormat === 'md_no_table') {
        download(noTableData.download_url, noTableData.filename)
        return
      }

      const noTableDownloadId = extractDownloadId(noTableData.download_url)
      if (!noTableDownloadId) {
        throw new Error('无表格文件转换后下载链接无效')
      }
      const finalData = await requestConvert(noTableDownloadId, targetFormat, {
        source_variant: 'summary_no_table'
      })
      download(finalData.download_url, finalData.filename)
    } catch (err) {
      conversionError.value = err instanceof Error ? err.message : '转换失败'
    } finally {
      noTableConverting.value.delete(key)
    }
  }

  const onConvertClick = (item, targetFormat) => {
    if (item.kind === 'summary_no_table') {
      convertNoTableAndDownload(item, targetFormat)
      return
    }
    convertAndDownload(item.downloadId, item.filename, targetFormat)
  }

  const generateFancyHtml = async (item) => {
    const key = fancyGenerateKey(item.downloadId)
    if (fancyGenerating.value.has(key)) {
      return
    }
    fancyGenerating.value.add(key)
    conversionError.value = ''
    try {
      const resp = await fetch('/api/summary/fancy-html', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          download_id: item.downloadId,
          history_run_id: props.historyRunId || null,
          summary_preset: item.presetName || null,
          summary_profile:
            item.summaryProfile || props.selectedSummaryProfile || null,
          api_key: props.requiresApiKey
            ? readLocalStorage(LOCAL_API_KEY_KEY) || null
            : null,
          deepseek_api_key: props.requiresApiKey
            ? readLocalStorage(LOCAL_DEEPSEEK_API_KEY_KEY) || null
            : null
        })
      })
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || '生成 Fancy HTML 失败')
      }
      if (data.history_detail) {
        emit('artifactGenerated', data.history_detail)
      } else {
        addGeneratedArtifact({
          kind: 'summary_fancy_html',
          download_url: data.download_url,
          filename: data.filename,
          summary_preset: item.presetName || '',
          summary_profile:
            item.summaryProfile || props.selectedSummaryProfile || ''
        })
      }
      download(data.download_url, data.filename)
    } catch (err) {
      conversionError.value =
        err instanceof Error ? err.message : '生成 Fancy HTML 失败'
    } finally {
      fancyGenerating.value.delete(key)
    }
  }

  const isConvertButtonLoading = (item, targetFormat) => {
    if (item.kind === 'summary_no_table') {
      return isNoTableConverting(item, targetFormat)
    }
    return isConverting(item.downloadId, targetFormat)
  }

  const isFancyPngConverting = (item, renderMode) =>
    isConverting(item.downloadId, 'png', { render_mode: renderMode })

  const convertFancyHtmlToPng = (item, renderMode) =>
    convertAndDownload(item.downloadId, item.filename, 'png', {
      render_mode: renderMode
    })

  const canDeleteMarkdownArtifact = (item) => {
    if (!props.allowDelete) {
      return false
    }
    if (!props.historyRunId) {
      return false
    }
    return item.kind === 'summary' || item.kind === 'summary_fancy_html'
  }

  const isDeleting = (item) => deletingKeys.value.has(item.key)

  const isFancyHtmlArtifact = (item) => item.kind === 'summary_fancy_html'

  const requestDeleteArtifact = (item) => {
    if (!canDeleteMarkdownArtifact(item) || isDeleting(item)) {
      return
    }
    deleteConfirmItem.value = item
  }

  const cancelDeleteArtifact = () => {
    if (!deleteConfirmItem.value) {
      return
    }
    if (isDeleting(deleteConfirmItem.value)) {
      return
    }
    deleteConfirmItem.value = null
  }

  const deletePreviewNames = computed(() => {
    const item = deleteConfirmItem.value
    if (!item) {
      return []
    }
    const noTable = displayItems.value.find(
      (candidate) =>
        candidate.parentSummaryRowId &&
        candidate.parentSummaryRowId === item.summaryRowId &&
        candidate.kind === 'summary_no_table'
    )
    const table = displayItems.value.find(
      (candidate) =>
        candidate.parentSummaryRowId &&
        candidate.parentSummaryRowId === item.summaryRowId &&
        candidate.kind === 'summary_table_md'
    )
    const fancy = displayItems.value.find(
      (candidate) =>
        candidate.parentSummaryRowId &&
        candidate.parentSummaryRowId === item.summaryRowId &&
        candidate.kind === 'summary_fancy_html'
    )
    return [
      item.displayName,
      noTable ? noTable.displayName : `${item.displayName}_无表格`,
      fancy
        ? fancy.displayName
        : buildArtifactDisplayName(
            {
              filename: item.filename.replace(
                /_summary(\.[^.]+)?$/i,
                '_summary_fancy.html'
              ),
              kind: 'summary_fancy_html'
            },
            { bvid: props.bvid }
          ),
      table
        ? table.displayName
        : buildArtifactDisplayName(
            {
              filename: item.filename,
              kind: 'summary_table_md'
            },
            { bvid: props.bvid }
          )
    ]
  })

  const handleDeleteArtifact = async () => {
    const item = deleteConfirmItem.value
    if (!item) {
      return
    }
    if (!canDeleteMarkdownArtifact(item) || isDeleting(item)) {
      return
    }

    deleteError.value = ''
    deletingKeys.value.add(item.key)
    try {
      const resp = await fetch(
        `/api/history/${encodeURIComponent(props.historyRunId)}/artifacts/${encodeURIComponent(item.downloadId)}`,
        {
          method: 'DELETE'
        }
      )
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail || '删除文件失败')
      }
      emit('artifactDeleted', data)
      deleteConfirmItem.value = null
    } catch (err) {
      deleteError.value = err instanceof Error ? err.message : '删除文件失败'
    } finally {
      deletingKeys.value.delete(item.key)
    }
  }
</script>

<template>
  <div class="file-list">
    <p v-if="conversionError" class="inline-error">
      <AlertCircle :size="16" />
      <span>{{ conversionError }}</span>
    </p>
    <p v-if="deleteError" class="inline-error">
      <AlertCircle :size="16" />
      <span>{{ deleteError }}</span>
    </p>

    <div v-if="displayItems.length > 0" class="all-downloads">
      <p class="all-downloads-title">{{ title }}</p>
      <ul class="all-download-list">
        <li
          v-for="item in displayItems"
          :key="item.key"
          :class="[
            'all-download-item',
            {
              'all-download-item-wide': item.isWideLayout,
              'all-download-item-derived': item.derivedFromSummary
            }
          ]"
        >
          <div class="all-download-main">
            <div class="all-download-title-row">
              <p class="all-download-name">{{ item.displayName }}</p>
              <button
                v-if="canDeleteMarkdownArtifact(item)"
                class="all-download-delete-icon"
                type="button"
                :disabled="isDeleting(item)"
                :title="
                  item.kind === 'summary_fancy_html'
                    ? '删除该 Fancy HTML'
                    : '删除该总结'
                "
                :aria-label="
                  item.kind === 'summary_fancy_html'
                    ? '删除该 Fancy HTML'
                    : '删除该总结'
                "
                @click="requestDeleteArtifact(item)"
              >
                <LoaderCircle v-if="isDeleting(item)" :size="14" class="spin" />
                <Trash2 v-else :size="14" />
              </button>
            </div>
            <span class="all-download-type">{{ item.fileType }}</span>
            <span
              v-if="item.presetLabel"
              class="all-download-type all-download-type-preset"
            >
              {{ item.presetLabel }}
            </span>
            <span
              v-if="item.modelProfileLabel"
              class="all-download-type all-download-type-profile"
            >
              {{ item.modelProfileLabel }}
            </span>
            <span
              v-if="item.derivedFromSummary"
              class="all-download-type all-download-type-derived"
            >
              派生自总结
            </span>
            <span v-if="item.noTableBadge" class="all-download-type"
              >无表格</span
            >
            <p v-if="item.derivedFromSummary" class="all-download-derived-note">
              来源：{{
                item.parentSummaryName || '对应总结'
              }}。删除父总结将同时清理此派生文件。
            </p>
          </div>
          <div class="all-download-actions">
            <button
              class="download download-sm"
              type="button"
              :disabled="isPrimaryConverting(item)"
              @click="handlePrimaryAction(item)"
            >
              <LoaderCircle
                v-if="isPrimaryConverting(item)"
                :size="14"
                class="spin"
              />
              <template v-else>
                <component :is="getFormatIcon(item.fileType)" :size="14" />
                <span>{{ getFormatLabel(item.fileType) }}</span>
              </template>
            </button>
            <button
              v-if="item.kind === 'summary_fancy_html'"
              class="download download-sm"
              type="button"
              :disabled="isFancyPngConverting(item, 'desktop')"
              @click="convertFancyHtmlToPng(item, 'desktop')"
            >
              <LoaderCircle
                v-if="isFancyPngConverting(item, 'desktop')"
                :size="14"
                class="spin"
              />
              <template v-else>
                <component :is="getFormatIcon('png')" :size="14" />
                <span>PNG Desktop</span>
              </template>
            </button>
            <button
              v-if="item.kind === 'summary_fancy_html'"
              class="download download-sm"
              type="button"
              :disabled="isFancyPngConverting(item, 'mobile')"
              @click="convertFancyHtmlToPng(item, 'mobile')"
            >
              <LoaderCircle
                v-if="isFancyPngConverting(item, 'mobile')"
                :size="14"
                class="spin"
              />
              <template v-else>
                <component :is="getFormatIcon('png')" :size="14" />
                <span>PNG Mobile</span>
              </template>
            </button>
            <template v-if="canConvert(item.kind)">
              <button
                v-if="item.kind === 'summary' || item.kind === 'rag_answer'"
                class="download download-sm"
                type="button"
                :disabled="isFancyGenerating(item)"
                @click="generateFancyHtml(item)"
              >
                <LoaderCircle
                  v-if="isFancyGenerating(item)"
                  :size="14"
                  class="spin"
                />
                <template v-else>
                  <component :is="getFormatIcon('html')" :size="14" />
                  <span>Fancy HTML</span>
                </template>
              </button>
              <button
                class="download download-sm"
                type="button"
                :disabled="isConvertButtonLoading(item, 'txt')"
                @click="onConvertClick(item, 'txt')"
              >
                <LoaderCircle
                  v-if="isConvertButtonLoading(item, 'txt')"
                  :size="14"
                  class="spin"
                />
                <template v-else>
                  <component :is="getFormatIcon('txt')" :size="14" />
                  <span>{{ getFormatLabel('txt') }}</span>
                </template>
              </button>
              <button
                class="download download-sm"
                type="button"
                :disabled="isConvertButtonLoading(item, 'pdf')"
                @click="onConvertClick(item, 'pdf')"
              >
                <LoaderCircle
                  v-if="isConvertButtonLoading(item, 'pdf')"
                  :size="14"
                  class="spin"
                />
                <template v-else>
                  <component :is="getFormatIcon('pdf')" :size="14" />
                  <span>{{ getFormatLabel('pdf') }}</span>
                </template>
              </button>
              <button
                class="download download-sm"
                type="button"
                :disabled="isConvertButtonLoading(item, 'png')"
                @click="onConvertClick(item, 'png')"
              >
                <LoaderCircle
                  v-if="isConvertButtonLoading(item, 'png')"
                  :size="14"
                  class="spin"
                />
                <template v-else>
                  <component :is="getFormatIcon('png')" :size="14" />
                  <span>{{ getFormatLabel('png') }}</span>
                </template>
              </button>
            </template>
          </div>
        </li>
      </ul>
    </div>

    <div
      v-if="allowDelete && deleteConfirmItem"
      class="modal-overlay"
      @click="cancelDeleteArtifact"
    >
      <div class="modal-content" @click.stop>
        <h3>
          {{
            isFancyHtmlArtifact(deleteConfirmItem)
              ? '确认删除 Fancy HTML'
              : '确认删除总结'
          }}
        </h3>
        <p v-if="isFancyHtmlArtifact(deleteConfirmItem)">
          此操作将删除该 Fancy HTML 文件，无法恢复：
        </p>
        <p v-else>此操作会一次性删除以下派生文件，并且无法恢复：</p>
        <ul class="delete-preview-list">
          <li v-if="isFancyHtmlArtifact(deleteConfirmItem)">
            {{ deleteConfirmItem.displayName }}
          </li>
          <li v-else v-for="name in deletePreviewNames" :key="name">
            {{ name }}
          </li>
        </ul>
        <div class="modal-actions">
          <button
            class="cancel-button"
            type="button"
            :disabled="isDeleting(deleteConfirmItem)"
            @click="cancelDeleteArtifact"
          >
            取消
          </button>
          <button
            class="confirm-delete-button"
            type="button"
            :disabled="isDeleting(deleteConfirmItem)"
            @click="handleDeleteArtifact"
          >
            <LoaderCircle
              v-if="isDeleting(deleteConfirmItem)"
              :size="16"
              class="spin"
            />
            <Trash2 v-else :size="16" />
            <span>{{
              isDeleting(deleteConfirmItem) ? '删除中...' : '确认删除'
            }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
  .file-list {
    margin-top: 0;
  }

  .delete-preview-list {
    margin: -6px 0 16px;
    padding-left: 18px;
    color: var(--text-soft);
    font-size: 0.88rem;
    line-height: 1.6;
  }

  /* ─── Download button ────────────────────────────────────────── */

  .download {
    margin-top: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border-radius: 13px;
    font-size: 0.95rem;
    font-weight: 700;
    cursor: pointer;
    min-height: 46px;
    padding: 0 16px;
    transition:
      transform 0.16s ease,
      box-shadow 0.2s ease,
      opacity 0.2s ease;
    border: 1px solid #99d9d2;
    color: #0f766e;
    background: linear-gradient(145deg, #f6fffd, #ecfeff);
    box-shadow: 0 2px 6px rgba(15, 118, 110, 0.08);
  }

  .download:hover {
    transform: translateY(-1px);
    border-color: #67c9be;
    background: linear-gradient(145deg, #f0fdfa, #e6fffb);
    box-shadow: 0 6px 16px rgba(15, 118, 110, 0.12);
  }

  .download:disabled {
    opacity: 0.64;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }

  .download-sm {
    margin-top: 0;
    min-height: 40px;
    min-width: 132px;
    padding: 0 14px;
    font-size: 0.88rem;
  }

  /* ─── File list ──────────────────────────────────────────────── */

  .all-downloads {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px dashed rgba(20, 184, 166, 0.35);
  }

  .all-downloads-title {
    margin: 0 0 10px;
    color: #0f766e;
    font-size: 0.83rem;
    font-weight: 700;
  }

  .all-download-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: grid;
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .all-download-item {
    display: flex;
    flex-direction: row;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
    border: 1px solid rgba(20, 184, 166, 0.22);
    border-radius: 12px;
    background: rgba(255, 255, 255, 0.62);
    padding: 12px;
  }

  .all-download-item-derived {
    margin-left: 22px;
    border-style: dashed;
    background: rgba(248, 250, 252, 0.78);
    position: relative;
  }

  .all-download-item-derived::before {
    content: '';
    position: absolute;
    left: -14px;
    top: 16px;
    bottom: 16px;
    width: 2px;
    border-radius: 999px;
    background: rgba(148, 163, 184, 0.65);
  }

  .all-download-item-derived::after {
    content: '';
    position: absolute;
    left: -14px;
    top: 26px;
    width: 10px;
    height: 2px;
    border-radius: 999px;
    background: rgba(148, 163, 184, 0.65);
  }

  .all-download-main {
    display: flex;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 8px;
    flex: 1;
    min-width: 0;
  }

  .all-download-title-row {
    flex-basis: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    min-width: 0;
  }

  .all-download-name {
    flex: 1;
    min-width: 0;
    margin: 0;
    color: #0f172a;
    font-size: 0.99rem;
    font-weight: 700;
    line-height: 1.3;
    word-break: break-all;
  }

  .all-download-delete-icon {
    border: none;
    background: transparent;
    color: #dc2626;
    padding: 2px;
    border-radius: 8px;
    min-width: 24px;
    min-height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
    transition:
      background-color 0.2s ease,
      color 0.2s ease;
  }

  .all-download-delete-icon:hover:not(:disabled) {
    background: rgba(254, 226, 226, 0.9);
    color: #b91c1c;
  }

  .all-download-delete-icon:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .all-download-type {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
    padding: 0 8px;
    border-radius: 999px;
    border: 1px solid #bae6fd;
    background: #eff6ff;
    color: #0c4a6e;
    font-size: 0.74rem;
    font-weight: 700;
  }

  .all-download-type-preset {
    border-color: #fcd34d;
    background: #fffbeb;
    color: #92400e;
  }

  .all-download-type-profile {
    border-color: #86efac;
    background: #f0fdf4;
    color: #166534;
  }

  .all-download-type-derived {
    border-color: #cbd5e1;
    background: #f8fafc;
    color: #475569;
  }

  .all-download-derived-note {
    flex-basis: 100%;
    margin: 0;
    font-size: 0.8rem;
    color: #64748b;
  }

  .all-download-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex-shrink: 0;
    gap: 8px;
    flex-wrap: wrap;
  }

  /* ─── Responsive ─────────────────────────────────────────────── */

  @media (max-width: 640px) {
    .download {
      width: 100%;
    }

    .all-download-item {
      flex-direction: column;
      align-items: stretch;
    }

    .all-download-item-derived {
      margin-left: 10px;
    }

    .all-download-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      width: 100%;
      gap: 8px;
    }

    .all-download-actions .download-sm {
      min-width: 0;
      width: 100%;
    }
  }
</style>
