<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { History, Sparkles } from 'lucide-vue-next';
import ProcessView from './components/ProcessView.vue';
import HistoryView from './components/HistoryView.vue';

// ─── View switching ──────────────────────────────────────────────
const currentView = ref('process'); // "process" | "history"

// ─── Summary configuration state ─────────────────────────────────
const summaryPresets = ref([]);
const summaryDefaultPreset = ref('');
const summaryProfiles = ref([]);
const selectedSummaryPreset = ref('');
const selectedSummaryProfile = ref('');
const summaryPresetError = ref('');
const summaryProfileError = ref('');
const isLoadingSummaryPresets = ref(false);
const isLoadingSummaryProfiles = ref(false);
const tabBarRef = ref(null);
const processTabRef = ref(null);
const historyTabRef = ref(null);
const tabIndicatorStyle = ref({
  width: '0px',
  transform: 'translateX(0px)',
});

const parseJsonSafely = async (resp, fallbackMessage) => {
  const raw = await resp.text();
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`${fallbackMessage}（服务返回了非 JSON 响应，HTTP ${resp.status}）`);
  }
};

const pickApiError = (resp, data, fallbackMessage) => {
  if (
    data &&
    typeof data === 'object' &&
    typeof data.detail === 'string' &&
    data.detail.trim()
  ) {
    return data.detail;
  }
  return `${fallbackMessage}（HTTP ${resp.status}）`;
};

const loadSummaryPresets = async () => {
  isLoadingSummaryPresets.value = true;
  summaryPresetError.value = '';
  try {
    const resp = await fetch('/api/summary-presets');
    const data = await parseJsonSafely(resp, '获取总结 presets 失败');

    if (!resp.ok) {
      throw new Error(pickApiError(resp, data, '获取总结 presets 失败'));
    }
    if (!data || typeof data !== 'object') {
      throw new Error('获取总结 presets 失败（服务返回空响应）');
    }

    const presets = Array.isArray(data.presets) ? data.presets : [];
    summaryPresets.value = presets;
    if (presets.length === 0) {
      summaryDefaultPreset.value = '';
      selectedSummaryPreset.value = '';
      return;
    }

    const fallback = presets[0].name;
    summaryDefaultPreset.value = data.default_preset || fallback;
    selectedSummaryPreset.value =
      data.selected_preset || summaryDefaultPreset.value || fallback;
  } catch (err) {
    console.error(err);
    summaryPresets.value = [];
    summaryDefaultPreset.value = '';
    selectedSummaryPreset.value = '';
    summaryPresetError.value =
      err instanceof Error
        ? `preset 加载失败：${err.message}`
        : 'preset 加载失败，请检查后端服务是否已启动';
  } finally {
    isLoadingSummaryPresets.value = false;
  }
};

const loadSummaryProfiles = async () => {
  isLoadingSummaryProfiles.value = true;
  summaryProfileError.value = '';
  try {
    const resp = await fetch('/api/summarize-profiles');
    const data = await parseJsonSafely(resp, '获取总结模型配置失败');

    if (!resp.ok) {
      throw new Error(pickApiError(resp, data, '获取总结模型配置失败'));
    }
    if (!data || typeof data !== 'object') {
      throw new Error('获取总结模型配置失败（服务返回空响应）');
    }

    const profiles = Array.isArray(data.profiles) ? data.profiles : [];
    summaryProfiles.value = profiles;
    if (profiles.length === 0) {
      selectedSummaryProfile.value = '';
      return;
    }

    const fallback = profiles[0].name;
    selectedSummaryProfile.value =
      data.selected_profile || data.default_profile || fallback;
  } catch (err) {
    console.error(err);
    summaryProfiles.value = [];
    selectedSummaryProfile.value = '';
    summaryProfileError.value =
      err instanceof Error
        ? `模型配置加载失败：${err.message}`
        : '模型配置加载失败，请检查后端服务是否已启动';
  } finally {
    isLoadingSummaryProfiles.value = false;
  }
};

const updateTabIndicator = () => {
  const bar = tabBarRef.value;
  const activeButton = currentView.value === 'process' ? processTabRef.value : historyTabRef.value;
  if (!bar || !activeButton) {
    return;
  }

  const barRect = bar.getBoundingClientRect();
  const buttonRect = activeButton.getBoundingClientRect();
  const offsetX = buttonRect.left - barRect.left;

  tabIndicatorStyle.value = {
    width: `${buttonRect.width}px`,
    transform: `translateX(${offsetX}px)`,
  };
};

onMounted(() => {
  void nextTick(updateTabIndicator);
  window.addEventListener('resize', updateTabIndicator);
  void Promise.all([loadSummaryProfiles(), loadSummaryPresets()]);
});

watch(currentView, async () => {
  await nextTick();
  updateTabIndicator();
});

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateTabIndicator);
});
</script>

<template>
  <main class="shell">
    <div class="ambient ambient-left"></div>
    <div class="ambient ambient-right"></div>

    <!-- Tab bar -->
    <nav ref="tabBarRef" class="tab-bar">
      <span class="tab-indicator" :style="tabIndicatorStyle" aria-hidden="true"></span>
      <button
        ref="processTabRef"
        class="tab-button"
        :class="{ active: currentView === 'process' }"
        @click="currentView = 'process'"
      >
        <Sparkles :size="16" />
        <span>新建转录</span>
      </button>
      <button
        ref="historyTabRef"
        class="tab-button"
        :class="{ active: currentView === 'history' }"
        @click="currentView = 'history'"
      >
        <History :size="16" />
        <span>历史记录</span>
      </button>
    </nav>

    <!-- Process View -->
    <ProcessView
      v-if="currentView === 'process'"
      :summary-presets="summaryPresets"
      :summary-default-preset="summaryDefaultPreset"
      :selected-summary-preset="selectedSummaryPreset"
      :summary-profiles="summaryProfiles"
      :selected-summary-profile="selectedSummaryProfile"
      :summary-preset-error="summaryPresetError"
      :summary-profile-error="summaryProfileError"
      :is-loading-summary-presets="isLoadingSummaryPresets"
      :is-loading-summary-profiles="isLoadingSummaryProfiles"
      @update:selected-summary-preset="selectedSummaryPreset = $event"
      @update:selected-summary-profile="selectedSummaryProfile = $event"
      @load-summary-presets="loadSummaryPresets"
      @load-summary-profiles="loadSummaryProfiles"
    />

    <!-- History View -->
    <HistoryView
      v-if="currentView === 'history'"
      :summary-presets="summaryPresets"
      :summary-default-preset="summaryDefaultPreset"
      :selected-summary-preset="selectedSummaryPreset"
      :summary-profiles="summaryProfiles"
      :selected-summary-profile="selectedSummaryProfile"
    />
  </main>
</template>
