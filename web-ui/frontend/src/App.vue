<script setup>
  import {
    computed,
    nextTick,
    onBeforeUnmount,
    onMounted,
    ref,
    watch
  } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import { Brain, History, KeyRound, Sparkles } from 'lucide-vue-next'
  import { usePublicCredentials } from './composables/usePublicCredentials'
  import { useRuntimeFeatures } from './composables/useRuntimeFeatures'
  import { useSummaryConfig } from './composables/useSummaryConfig'

  const route = useRoute()
  const router = useRouter()
  const { isOpenPublic, loadRuntimeFeatures } = useRuntimeFeatures()
  const { refreshCredentials } = usePublicCredentials()
  const { initializeSummaryConfig } = useSummaryConfig()
  const tabBarRef = ref(null)
  const tabIndicatorStyle = ref({
    width: '0px',
    transform: 'translateX(0px)'
  })

  // Active tab detection
  const currentView = computed(() => {
    const path = route.path
    if (path.startsWith('/process')) return 'process'
    if (path.startsWith('/history')) return 'history'
    if (path.startsWith('/rag')) return 'rag'
    if (path.startsWith('/settings')) return 'settings'
    return 'process'
  })

  // Tab bar indicator animation
  const tabRefs = ref({})
  const setTabRef = (view, el) => {
    if (el) tabRefs.value[view] = el
  }

  const updateTabIndicator = () => {
    const bar = tabBarRef.value
    const activeButton = tabRefs.value[currentView.value]
    if (!bar || !activeButton) {
      return
    }

    const barRect = bar.getBoundingClientRect()
    const buttonRect = activeButton.getBoundingClientRect()
    const offsetX = buttonRect.left - barRect.left

    tabIndicatorStyle.value = {
      width: `${buttonRect.width}px`,
      transform: `translateX(${offsetX}px)`
    }
  }

  const navigateTo = (path) => {
    router.push(path)
  }

  onMounted(() => {
    void nextTick(updateTabIndicator)
    window.addEventListener('resize', updateTabIndicator)
    refreshCredentials()
    void (async () => {
      await loadRuntimeFeatures()
      await initializeSummaryConfig()
      await nextTick()
      updateTabIndicator()
    })()
  })

  watch(currentView, async () => {
    await nextTick()
    updateTabIndicator()
  })

  watch(isOpenPublic, async (openPublic) => {
    if (!openPublic && route.path === '/settings') {
      router.push('/process')
      return
    }
    await nextTick()
    updateTabIndicator()
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', updateTabIndicator)
  })
</script>

<template>
  <main class="shell">
    <div class="ambient ambient-left"></div>
    <div class="ambient ambient-right"></div>

    <!-- Tab bar -->
    <nav ref="tabBarRef" class="tab-bar">
      <span
        class="tab-indicator"
        :style="tabIndicatorStyle"
        aria-hidden="true"
      ></span>
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

    <RouterView />
  </main>
</template>

<style scoped>
  /* ─── Shell & Ambient ────────────────────────────────────────── */

  .shell {
    position: relative;
    min-height: 100vh;
    padding: clamp(12px, 2vw, 24px) clamp(24px, 4vw, 48px)
      clamp(24px, 4vw, 48px);
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
    box-shadow:
      0 4px 12px rgba(15, 23, 42, 0.04),
      inset 0 1px 1px rgba(255, 255, 255, 0.6);
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
    transition:
      transform 0.34s cubic-bezier(0.16, 1, 0.3, 1),
      width 0.34s cubic-bezier(0.16, 1, 0.3, 1);
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
    transition:
      color 0.24s ease,
      transform 0.2s ease;
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
      overflow-x: auto;
      scrollbar-width: none;
    }

    .tab-bar::-webkit-scrollbar {
      display: none;
    }

    .tab-button {
      flex: 1 0 auto;
      justify-content: center;
      min-width: 0;
      padding: 9px 10px;
      font-size: 0.84rem;
    }

    .tab-button span {
      white-space: nowrap;
    }
  }
</style>
