<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Brain, History, KeyRound, Sparkles } from 'lucide-vue-next';

const route = useRoute();
const router = useRouter();

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
const tabIndicatorStyle = ref({
  width: '0px',
  transform: 'translateX(0px)',
});
const runtimeFeatures = ref({
  mode: 'default',
  allow_upload_audio: true,
  allow_delete: true,
  requires_user_api_key: false,
  api_key_configured: true,
});

const isOpenPublic = computed(() => runtimeFeatures.value.mode === 'open-public');

// Active tab detection
const currentView = computed(() => {
  const path = route.path;
  if (path.startsWith('/process')) return 'process';
  if (path.startsWith('/history')) return 'history';
  if (path.startsWith('/rag')) return 'rag';
  if (path.startsWith('/settings')) return 'settings';
  return 'process';
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

const loadRuntimeFeatures = async () => {
  try {
    const resp = await fetch('/api/runtime');
    const data = await parseJsonSafely(resp, '获取运行时配置失败');

    if (!resp.ok) {
      throw new Error(pickApiError(resp, data, '获取运行时配置失败'));
    }
    if (!data || typeof data !== 'object') {
      throw new Error('获取运行时配置失败（服务返回空响应）');
    }

    runtimeFeatures.value = {
      mode: data.mode === 'open-public' ? 'open-public' : 'default',
      allow_upload_audio: Boolean(data.allow_upload_audio),
      allow_delete: Boolean(data.allow_delete),
      requires_user_api_key: Boolean(data.requires_user_api_key),
      api_key_configured: Boolean(data.api_key_configured),
    };
  } catch (err) {
    console.error(err);
    runtimeFeatures.value = {
      mode: 'default',
      allow_upload_audio: true,
      allow_delete: true,
      requires_user_api_key: false,
      api_key_configured: true,
    };
  }
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

// Tab bar indicator animation
const tabRefs = ref({});
const setTabRef = (view, el) => {
  if (el) tabRefs.value[view] = el;
};

const updateTabIndicator = () => {
  const bar = tabBarRef.value;
  const activeButton = tabRefs.value[currentView.value];
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

const onApiKeyUpdated = async () => {
  await loadRuntimeFeatures();
  await loadSummaryProfiles();
};

const navigateTo = (path) => {
  router.push(path);
};

onMounted(() => {
  void nextTick(updateTabIndicator);
  window.addEventListener('resize', updateTabIndicator);
  void (async () => {
    await loadRuntimeFeatures();
    await Promise.all([loadSummaryProfiles(), loadSummaryPresets()]);
    await nextTick();
    updateTabIndicator();
  })();
});

watch(currentView, async () => {
  await nextTick();
  updateTabIndicator();
});

watch(isOpenPublic, async (openPublic) => {
  if (!openPublic && route.path === '/settings') {
    router.push('/process');
    return;
  }
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
        :ref="(el) => setTabRef('process', el)"
        class="tab-button"
        :class="{ active: currentView === 'process' }"
        @click="navigateTo('/process')"
      >
        <Sparkles :size="16" />
        <span>新建转录</span>
      </button>
      <button
        :ref="(el) => setTabRef('history', el)"
        class="tab-button"
        :class="{ active: currentView === 'history' }"
        @click="navigateTo('/history')"
      >
        <History :size="16" />
        <span>历史记录</span>
      </button>
      <button
        :ref="(el) => setTabRef('rag', el)"
        class="tab-button"
        :class="{ active: currentView === 'rag' }"
        @click="navigateTo('/rag')"
      >
        <Brain :size="16" />
        <span>知识库</span>
      </button>
      <button
        v-if="isOpenPublic"
        :ref="(el) => setTabRef('settings', el)"
        class="tab-button"
        :class="{ active: currentView === 'settings' }"
        @click="navigateTo('/settings')"
      >
        <KeyRound :size="16" />
        <span>API Key</span>
      </button>
    </nav>

    <!-- Routed views -->
    <RouterView
      v-slot="{ Component }"
    >
      <component
        :is="Component"
        :summary-presets="summaryPresets"
        :summary-default-preset="summaryDefaultPreset"
        :selected-summary-preset="selectedSummaryPreset"
        :summary-profiles="summaryProfiles"
        :selected-summary-profile="selectedSummaryProfile"
        :summary-preset-error="summaryPresetError"
        :summary-profile-error="summaryProfileError"
        :is-loading-summary-presets="isLoadingSummaryPresets"
        :is-loading-summary-profiles="isLoadingSummaryProfiles"
        :allow-upload="runtimeFeatures.allow_upload_audio"
        :requires-api-key="runtimeFeatures.requires_user_api_key"
        :api-key-configured="runtimeFeatures.api_key_configured"
        :allow-delete="runtimeFeatures.allow_delete"
        @update:selected-summary-preset="selectedSummaryPreset = $event"
        @update:selected-summary-profile="selectedSummaryProfile = $event"
        @load-summary-presets="loadSummaryPresets"
        @load-summary-profiles="loadSummaryProfiles"
        @api-key-updated="onApiKeyUpdated"
      />
    </RouterView>
  </main>
</template>

<style scoped>
/* ─── Shell & Ambient ────────────────────────────────────────── */

.shell {
  position: relative;
  min-height: 100vh;
  padding: clamp(24px, 4vw, 48px);
  overflow: hidden;
}

.ambient {
  position: absolute;
  border-radius: 999px;
  filter: blur(80px);
  opacity: 0.35;
  pointer-events: none;
  animation: float 16s ease-in-out infinite;
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
  margin: 0 auto 32px;
  display: inline-flex;
  gap: 4px;
  padding: 6px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.5);
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04), inset 0 1px 1px rgba(255, 255, 255, 0.6);
  isolation: isolate;
}

.tab-indicator {
  position: absolute;
  top: 6px;
  left: 0;
  bottom: 6px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
  pointer-events: none;
  transition: transform 0.34s cubic-bezier(0.16, 1, 0.3, 1), width 0.34s cubic-bezier(0.16, 1, 0.3, 1);
  z-index: 0;
}

.tab-button {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  border: none;
  border-radius: 14px;
  background: transparent;
  color: var(--text-muted);
  font-size: 0.9rem;
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
