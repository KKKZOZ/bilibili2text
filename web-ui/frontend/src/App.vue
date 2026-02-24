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

<style scoped>
/* ─── Shell & Ambient ────────────────────────────────────────── */

.shell {
  position: relative;
  min-height: 100vh;
  padding: clamp(16px, 3vw, 36px);
  overflow: hidden;
}

.ambient {
  position: absolute;
  border-radius: 999px;
  filter: blur(65px);
  opacity: 0.52;
  pointer-events: none;
  animation: float 12s ease-in-out infinite;
}

.ambient-left {
  width: 360px;
  height: 360px;
  left: -130px;
  top: -110px;
  background: #7dd3fc;
}

.ambient-right {
  width: 420px;
  height: 420px;
  right: -180px;
  bottom: -150px;
  background: #99f6e4;
  animation-delay: 0.8s;
}

/* ─── Tab bar ────────────────────────────────────────────────── */

.tab-bar {
  position: relative;
  z-index: 2;
  max-width: 1160px;
  margin: 0 auto 20px;
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border-radius: 16px;
  border: 1px solid var(--panel-border);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
  isolation: isolate;
}

.tab-indicator {
  position: absolute;
  top: 4px;
  left: 0;
  bottom: 4px;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
  pointer-events: none;
  transition: transform 0.34s cubic-bezier(0.22, 1, 0.36, 1), width 0.34s cubic-bezier(0.22, 1, 0.36, 1);
  z-index: 0;
}

.tab-button {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px 18px;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: var(--text-muted);
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.24s ease, transform 0.2s ease;
}

.tab-button:hover {
  color: var(--text-soft);
}

.tab-button:active {
  transform: translateY(1px);
}

.tab-button.active {
  color: #0f766e;
}

.tab-button svg {
  transition: transform 0.26s ease;
}

.tab-button.active svg {
  transform: scale(1.04);
}

.tab-button:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px rgba(15, 118, 110, 0.28);
}

/* ─── Responsive ─────────────────────────────────────────────── */

@media (max-width: 640px) {
  .ambient {
    display: none;
  }

  .tab-bar {
    width: 100%;
  }

  .tab-button {
    flex: 1;
    justify-content: center;
    padding: 9px 12px;
    font-size: 0.84rem;
  }
}
</style>
