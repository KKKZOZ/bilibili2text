<script setup>
import { computed, ref } from 'vue';
import {
  AlertCircle,
  Braces,
  File,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Music,
  Trash2,
  Type,
} from 'lucide-vue-next';
import { useConversion } from '../composables/useConversion';
import { resolveFileType, buildArtifactDisplayName } from '../utils/fileUtils';

const props = defineProps({
  items: {
    type: Array,
    required: true,
  },
  summaryPresets: {
    type: Array,
    default: () => [],
  },
  summaryDefaultPreset: {
    type: String,
    default: '',
  },
  selectedSummaryPreset: {
    type: String,
    default: '',
  },
  summaryProfiles: {
    type: Array,
    default: () => [],
  },
  selectedSummaryProfile: {
    type: String,
    default: '',
  },
  bvid: {
    type: String,
    default: '',
  },
  title: {
    type: String,
    default: '基本文件',
  },
  historyRunId: {
    type: String,
    default: '',
  },
  filterKinds: {
    type: Array,
    default: () => [
      'markdown',
      'summary',
      'summary_no_table',
      'summary_table_md',
      'summary_table_pdf',
    ],
  },
});

const emit = defineEmits(['artifactDeleted']);

const { conversionError, convertAndDownload, isConverting, download } = useConversion();
const noTableConverting = ref(new Set());
const deleteError = ref('');
const deletingKeys = ref(new Set());
const deleteConfirmItem = ref(null);

const formatIconMap = {
  markdown: FileText,
  txt: Type,
  pdf: FileText,
  png: ImageIcon,
  json: Braces,
  音频: Music,
  audio: Music,
};

const normalizeFormatKey = (value) => (value || '').trim().toLowerCase();

const formatLabelMap = {
  markdown: 'Markdown',
  txt: 'TXT',
  pdf: 'PDF',
  png: 'PNG',
  json: 'JSON',
  音频: '音频',
  audio: '音频',
};

const getFormatIcon = (format) => formatIconMap[normalizeFormatKey(format)] || File;

const getFormatLabel = (format) =>
  formatLabelMap[normalizeFormatKey(format)] || format || '文件';

const resolveSummaryPresetLabel = (presetName) => {
  let effectiveName = (presetName || '').trim();
  if (!effectiveName || effectiveName === 'default') {
    effectiveName =
      props.summaryDefaultPreset || props.selectedSummaryPreset || 'default';
  }
  const matched = props.summaryPresets.find((item) => item.name === effectiveName);
  if (matched && typeof matched.label === 'string' && matched.label.trim()) {
    return matched.label.trim();
  }
  return effectiveName;
};

const isSummaryKind = (kind) =>
  kind === 'summary' ||
  kind === 'summary_text' ||
  kind === 'summary_no_table' ||
  kind === 'summary_table_md' ||
  kind === 'summary_table_pdf';

const isSummaryDerivedKind = (kind) =>
  kind === 'summary_no_table' || kind === 'summary_table_md' || kind === 'summary_table_pdf';

const resolveSummaryProfileLabel = (profileName) => {
  const effectiveName = (profileName || '').trim();
  if (!effectiveName) {
    return '';
  }
  const matched = props.summaryProfiles.find((item) => item.name === effectiveName);
  if (matched && typeof matched.name === 'string' && matched.name.trim()) {
    return matched.name.trim();
  }
  return effectiveName;
};

const resolveSummaryFamilyKey = (item, kind) => {
  if (!item || typeof item.filename !== 'string' || item.filename.trim() === '') {
    return '';
  }
  const stem = item.filename.replace(/\.[^.]*$/, '');
  if (kind === 'summary' || kind === 'summary_no_table' || kind === 'summary_text') {
    return stem;
  }
  if (kind === 'summary_table_md' || kind === 'summary_table_pdf') {
    return stem.replace(/_table$/i, '');
  }
  return '';
};

const displayItems = computed(() => {
  const formatPriority = {
    Markdown: 0,
    TXT: 1,
    PDF: 2,
    PNG: 3,
    JSON: 4,
    音频: 5,
  };
  const kindBaseOrder = {
    markdown: 100,
    summary: 200,
    summary_no_table: 210,
    summary_table_md: 220,
    summary_table_pdf: 221,
    text: 300,
    summary_text: 310,
    json: 400,
    audio: 500,
  };

  const toDisplayItem = (item, index, overrides = {}) => {
    const kind = overrides.kind || item.kind;
    const fileType = overrides.fileType || resolveFileType(item.filename, kind);
    const isDerivedFromSummary = isSummaryDerivedKind(kind);
    const displayName =
      overrides.displayName ||
      buildArtifactDisplayName(
        {
          ...item,
          kind,
        },
        { bvid: props.bvid }
      );

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
        kind === 'summary_table_md'
          ? resolveSummaryPresetLabel(item.presetName || '')
          : '',
      modelProfileLabel: isSummaryKind(kind)
        ? resolveSummaryProfileLabel(item.summaryProfile || '')
        : '',
      downloadId: item.url.split('/').pop(),
      summarySignature:
        overrides.summarySignature ||
        `${(item.presetName || '').trim()}::${(item.summaryProfile || '').trim()}`,
      summaryFamilyKey: overrides.summaryFamilyKey || resolveSummaryFamilyKey(item, kind),
      summaryRowId:
        overrides.summaryRowId ||
        (kind === 'summary' ? extractDownloadId(item.url) || `summary-${index}` : ''),
      parentSummaryRowId: overrides.parentSummaryRowId || '',
      order:
        overrides.order ??
        (kindBaseOrder[kind] !== undefined ? kindBaseOrder[kind] + index / 100 : 900 + index),
      isWideLayout: kind === 'markdown' || kind === 'summary_no_table',
      primaryTargetFormat: kind === 'summary_no_table' ? 'md_no_table' : '',
      noTableBadge: kind === 'summary_no_table',
      derivedFromSummary: isDerivedFromSummary,
    };
  };

  const rows = [];
  const filteredItems = props.items.filter((item) => props.filterKinds.includes(item.kind));
  const summaryRowsByFamily = new Map();
  const summaryRowsBySignature = new Map();

  // Phase 1: build summary roots and synthetic summary_no_table rows.
  filteredItems.forEach((item, index) => {
    if (item.kind === 'summary') {
      const summaryId = extractDownloadId(item.url) || `summary-${index}`;
      const signature = `${(item.presetName || '').trim()}::${(item.summaryProfile || '').trim()}`;
      const familyKey = resolveSummaryFamilyKey(item, 'summary');
      const summaryRow = toDisplayItem(item, index, {
        summaryRowId: summaryId,
        summarySignature: signature,
        summaryFamilyKey: familyKey,
      });
      rows.push(summaryRow);

      if (familyKey) {
        summaryRowsByFamily.set(familyKey, summaryRow);
      }
      const bucket = summaryRowsBySignature.get(signature) || [];
      bucket.push(summaryRow);
      summaryRowsBySignature.set(signature, bucket);

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
            summaryFamilyKey: familyKey,
          })
        );
      }
    }
  });

  // Phase 2: build non-summary rows and bind derived artifacts to parent summary.
  filteredItems.forEach((item, index) => {
    if (item.kind === 'summary') {
      return;
    }

    if (item.kind === 'summary_table_md' || item.kind === 'summary_table_pdf') {
      const signature = `${(item.presetName || '').trim()}::${(item.summaryProfile || '').trim()}`;
      const familyKey = resolveSummaryFamilyKey(item, item.kind);
      let parentSummary = familyKey ? summaryRowsByFamily.get(familyKey) || null : null;
      if (!parentSummary) {
        const sameSignature = summaryRowsBySignature.get(signature) || [];
        parentSummary = sameSignature.length > 0 ? sameSignature[sameSignature.length - 1] : null;
      }
      const derivedOffset = item.kind === 'summary_table_pdf' ? 0.25 : 0.2;
      rows.push(
        toDisplayItem(item, index, {
          parentSummaryRowId: parentSummary?.summaryRowId || '',
          summarySignature: signature,
          summaryFamilyKey: familyKey,
          order: parentSummary ? parentSummary.order + derivedOffset : undefined,
        })
      );
      return;
    }

    rows.push(toDisplayItem(item, index));
  });

  const sortedRows = rows
    .sort((a, b) => {
      if (a.order === b.order && a.formatPriority !== b.formatPriority) {
        return a.formatPriority - b.formatPriority;
      }
      return a.order - b.order;
    });

  const summaryNameById = new Map(
    sortedRows
      .filter((item) => item.kind === 'summary' && item.summaryRowId)
      .map((item) => [item.summaryRowId, item.displayName])
  );

  return sortedRows.map((item) => ({
    ...item,
    parentSummaryName: item.parentSummaryRowId
      ? summaryNameById.get(item.parentSummaryRowId) || ''
      : '',
  }));
});

const canConvert = (kind) => {
  return (
    kind === 'markdown' ||
    kind === 'summary' ||
    kind === 'summary_no_table' ||
    kind === 'summary_table_md'
  );
};

const isPrimaryConverting = (item) => {
  if (!item.primaryTargetFormat) {
    return false;
  }
  return isConverting(item.downloadId, item.primaryTargetFormat);
};

const handlePrimaryAction = (item) => {
  if (item.primaryTargetFormat) {
    convertAndDownload(item.downloadId, item.filename, item.primaryTargetFormat);
    return;
  }
  download(item.url, item.filename);
};

const noTableConvertKey = (downloadId, targetFormat) =>
  `${downloadId}-summary-no-table-${targetFormat}`;

const isNoTableConverting = (item, targetFormat) =>
  noTableConverting.value.has(noTableConvertKey(item.downloadId, targetFormat));

const requestConvert = async (downloadId, targetFormat) => {
  const resp = await fetch('/api/convert', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      download_id: downloadId,
      target_format: targetFormat,
    }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error(data.detail || '转换失败');
  }
  return data;
};

const extractDownloadId = (downloadUrl) => {
  if (typeof downloadUrl !== 'string') {
    return '';
  }
  return downloadUrl.split('/').pop() || '';
};

const convertNoTableAndDownload = async (item, targetFormat) => {
  const key = noTableConvertKey(item.downloadId, targetFormat);
  if (noTableConverting.value.has(key)) {
    return;
  }

  noTableConverting.value.add(key);
  conversionError.value = '';
  try {
    const noTableData = await requestConvert(item.downloadId, 'md_no_table');
    if (targetFormat === 'md_no_table') {
      download(noTableData.download_url, noTableData.filename);
      return;
    }

    const noTableDownloadId = extractDownloadId(noTableData.download_url);
    if (!noTableDownloadId) {
      throw new Error('无表格文件转换后下载链接无效');
    }
    const finalData = await requestConvert(noTableDownloadId, targetFormat);
    download(finalData.download_url, finalData.filename);
  } catch (err) {
    conversionError.value = err instanceof Error ? err.message : '转换失败';
  } finally {
    noTableConverting.value.delete(key);
  }
};

const onConvertClick = (item, targetFormat) => {
  if (item.kind === 'summary_no_table') {
    convertNoTableAndDownload(item, targetFormat);
    return;
  }
  convertAndDownload(item.downloadId, item.filename, targetFormat);
};

const isConvertButtonLoading = (item, targetFormat) => {
  if (item.kind === 'summary_no_table') {
    return isNoTableConverting(item, targetFormat);
  }
  return isConverting(item.downloadId, targetFormat);
};

const canDeleteMarkdownArtifact = (item) => {
  if (!props.historyRunId) {
    return false;
  }
  return item.kind === 'summary';
};

const isDeleting = (item) => deletingKeys.value.has(item.key);

const requestDeleteArtifact = (item) => {
  if (!canDeleteMarkdownArtifact(item) || isDeleting(item)) {
    return;
  }
  deleteConfirmItem.value = item;
};

const cancelDeleteArtifact = () => {
  if (!deleteConfirmItem.value) {
    return;
  }
  if (isDeleting(deleteConfirmItem.value)) {
    return;
  }
  deleteConfirmItem.value = null;
};

const deletePreviewNames = computed(() => {
  const item = deleteConfirmItem.value;
  if (!item) {
    return [];
  }
  const noTable = displayItems.value.find(
    (candidate) =>
      candidate.parentSummaryRowId &&
      candidate.parentSummaryRowId === item.summaryRowId &&
      candidate.kind === 'summary_no_table'
  );
  const table = displayItems.value.find(
    (candidate) =>
      candidate.parentSummaryRowId &&
      candidate.parentSummaryRowId === item.summaryRowId &&
      candidate.kind === 'summary_table_md'
  );
  return [
    item.displayName,
    noTable ? noTable.displayName : `${item.displayName}_无表格`,
    table
      ? table.displayName
      : buildArtifactDisplayName(
          {
            filename: item.filename,
            kind: 'summary_table_md',
          },
          { bvid: props.bvid }
        ),
  ];
});

const handleDeleteArtifact = async () => {
  const item = deleteConfirmItem.value;
  if (!item) {
    return;
  }
  if (!canDeleteMarkdownArtifact(item) || isDeleting(item)) {
    return;
  }

  deleteError.value = '';
  deletingKeys.value.add(item.key);
  try {
    const resp = await fetch(
      `/api/history/${encodeURIComponent(props.historyRunId)}/artifacts/${encodeURIComponent(item.downloadId)}`,
      {
        method: 'DELETE',
      }
    );
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || '删除文件失败');
    }
    emit('artifactDeleted', data);
    deleteConfirmItem.value = null;
  } catch (err) {
    deleteError.value = err instanceof Error ? err.message : '删除文件失败';
  } finally {
    deletingKeys.value.delete(item.key);
  }
};
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
              'all-download-item-derived': item.derivedFromSummary,
            },
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
                title="删除该总结"
                aria-label="删除该总结"
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
            <span v-if="item.noTableBadge" class="all-download-type">无表格</span>
            <p v-if="item.derivedFromSummary" class="all-download-derived-note">
              来源：{{ item.parentSummaryName || '对应总结' }}。删除父总结将同时清理此派生文件。
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
            <template v-if="canConvert(item.kind)">
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

    <div v-if="deleteConfirmItem" class="modal-overlay" @click="cancelDeleteArtifact">
      <div class="modal-content" @click.stop>
        <h3>确认删除总结</h3>
        <p>此操作会一次性删除以下 3 项，并且无法恢复：</p>
        <ul class="delete-preview-list">
          <li v-for="name in deletePreviewNames" :key="name">{{ name }}</li>
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
            <LoaderCircle v-if="isDeleting(deleteConfirmItem)" :size="16" class="spin" />
            <Trash2 v-else :size="16" />
            <span>{{ isDeleting(deleteConfirmItem) ? '删除中...' : '确认删除' }}</span>
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
</style>
