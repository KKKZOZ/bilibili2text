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
  bvid: {
    type: String,
    default: '',
  },
  title: {
    type: String,
    default: '基本文件',
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

const { conversionError, convertAndDownload, isConverting, download } = useConversion();
const noTableConverting = ref(new Set());

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

const displayItems = computed(() => {
  const formatPriority = {
    Markdown: 0,
    TXT: 1,
    PDF: 2,
    PNG: 3,
    JSON: 4,
    音频: 5,
  };

  const toDisplayItem = (item, index, overrides = {}) => {
    const kind = overrides.kind || item.kind;
    const fileType = overrides.fileType || resolveFileType(item.filename, kind);
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
        kind === 'summary' || kind === 'summary_text' || kind === 'summary_no_table'
          ? resolveSummaryPresetLabel(item.presetName || '')
          : '',
      downloadId: item.url.split('/').pop(),
      order: overrides.order ?? index,
      isWideLayout: kind === 'markdown' || kind === 'summary_no_table',
      primaryTargetFormat: kind === 'summary_no_table' ? 'md_no_table' : '',
      noTableBadge: kind === 'summary_no_table',
    };
  };

  const rows = props.items
    .filter((item) => props.filterKinds.includes(item.kind))
    .flatMap((item, index) => {
      const list = [toDisplayItem(item, index)];

      if (item.kind === 'summary' && props.filterKinds.includes('summary_no_table')) {
        list.push(
          toDisplayItem(item, index, {
            key: `${item.key || item.url || item.filename}-summary-no-table`,
            kind: 'summary_no_table',
            displayName: `${buildArtifactDisplayName(item, { bvid: props.bvid })}_无表格`,
            fileType: 'Markdown',
            order: index + 0.1,
          })
        );
      }

      return list;
    });

  return rows
    .sort((a, b) => {
      if (a.displayName === b.displayName && a.formatPriority !== b.formatPriority) {
        return a.formatPriority - b.formatPriority;
      }
      return a.order - b.order;
    });
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
</script>

<template>
  <div class="file-list">
    <p v-if="conversionError" class="inline-error">
      <AlertCircle :size="16" />
      <span>{{ conversionError }}</span>
    </p>

    <div v-if="displayItems.length > 0" class="all-downloads">
      <p class="all-downloads-title">{{ title }}</p>
      <ul class="all-download-list">
        <li
          v-for="item in displayItems"
          :key="item.key"
          :class="['all-download-item', { 'all-download-item-wide': item.isWideLayout }]"
        >
          <div class="all-download-main">
            <p class="all-download-name">{{ item.displayName }}</p>
            <span class="all-download-type">{{ item.fileType }}</span>
            <span v-if="item.presetLabel" class="all-download-type">
              {{ item.presetLabel }}
            </span>
            <span v-if="item.noTableBadge" class="all-download-type">无表格</span>
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
  </div>
</template>

<style scoped>
.file-list {
  margin-top: 0;
}
</style>
