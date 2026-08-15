<script setup>
  import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import {
    AudioLines,
    Brain,
    History,
    KeyRound,
    Sparkles
  } from 'lucide-vue-next'
  import { usePublicCredentials } from './composables/usePublicCredentials'
  import { startJobCompletionNotificationMonitor } from './composables/useJobNotifications'
  import { useRuntimeFeatures } from './composables/useRuntimeFeatures'
  import { useSummaryConfig } from './composables/useSummaryConfig'

  const route = useRoute()
  const router = useRouter()
  const { isOpenPublic, loadRuntimeFeatures } = useRuntimeFeatures()
  const { refreshCredentials } = usePublicCredentials()
  const { initializeSummaryConfig } = useSummaryConfig()
  let stopJobCompletionNotificationMonitor = null

  const navigation = computed(() => [
    { key: 'process', label: '新建转录', path: '/process', icon: Sparkles },
    { key: 'history', label: '历史记录', path: '/history', icon: History },
    { key: 'rag', label: '知识库', path: '/rag', icon: Brain },
    ...(isOpenPublic.value
      ? [
          {
            key: 'settings',
            label: 'API Key 配置',
            path: '/settings',
            icon: KeyRound
          }
        ]
      : [])
  ])

  const currentView = computed(() => {
    const path = route.path
    if (path.startsWith('/history')) return 'history'
    if (path.startsWith('/rag')) return 'rag'
    if (path.startsWith('/settings')) return 'settings'
    return 'process'
  })

  const currentPage = computed(
    () =>
      navigation.value.find((item) => item.key === currentView.value) || {
        label: '新建转录'
      }
  )

  onMounted(() => {
    stopJobCompletionNotificationMonitor =
      startJobCompletionNotificationMonitor()
    refreshCredentials()
    void initializeSummaryConfig()
    void (async () => {
      await loadRuntimeFeatures()
      if (!isOpenPublic.value && route.path === '/settings') {
        router.push('/process')
      }
    })()
  })

  onBeforeUnmount(() => {
    stopJobCompletionNotificationMonitor?.()
  })

  watch(isOpenPublic, (openPublic) => {
    if (!openPublic && route.path === '/settings') router.push('/process')
  })
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-inner">
        <RouterLink
          class="brand-lockup"
          to="/process"
          aria-label="返回新建转录"
        >
          <span class="brand-mark"><AudioLines :size="20" /></span>
          <span class="brand-copy">
            <strong>bilibili-to-text</strong>
          </span>
        </RouterLink>

        <nav class="top-tabs" aria-label="主导航">
          <button
            v-for="item in navigation"
            :key="item.key"
            type="button"
            :class="{ active: currentView === item.key }"
            @click="router.push(item.path)"
          >
            <component :is="item.icon" :size="17" />
            <span>{{ item.label }}</span>
          </button>
        </nav>
      </div>
    </header>

    <main class="workspace-content">
      <header class="page-heading">
        <h1>{{ currentPage.label }}</h1>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
  .app-shell {
    min-height: 100vh;
  }

  .topbar {
    position: sticky;
    z-index: 100;
    top: 0;
    border-bottom: 1px solid #dbe1e8;
    background: rgba(255, 255, 255, 0.96);
    backdrop-filter: blur(12px);
  }

  .topbar-inner {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    width: 100%;
    max-width: 1440px;
    min-height: 64px;
    margin: 0 auto;
    padding: 0 clamp(28px, 4vw, 56px);
  }

  .brand-lockup {
    display: flex;
    align-items: center;
    gap: 10px;
    padding-right: 30px;
    border-radius: 7px;
    color: var(--text-main);
    text-decoration: none;
  }

  .brand-lockup:focus-visible {
    outline: 0;
    box-shadow: 0 0 0 3px rgba(15, 143, 131, 0.14);
  }

  .brand-mark {
    display: grid;
    flex: 0 0 auto;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 7px;
    background: #101820;
    color: #5eead4;
  }

  .brand-copy {
    min-width: 0;
  }

  .brand-copy strong {
    font-size: 0.88rem;
    line-height: 1.2;
    white-space: nowrap;
  }

  .top-tabs {
    display: flex;
    align-self: stretch;
    min-width: 0;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .top-tabs::-webkit-scrollbar {
    display: none;
  }

  .top-tabs button {
    position: relative;
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    gap: 7px;
    min-width: 110px;
    padding: 0 16px;
    border: 0;
    background: transparent;
    color: #687584;
    font: inherit;
    font-size: 0.82rem;
    font-weight: 700;
    cursor: pointer;
  }

  .top-tabs button::after {
    position: absolute;
    right: 14px;
    bottom: 0;
    left: 14px;
    height: 2px;
    background: transparent;
    content: '';
  }

  .top-tabs button:hover {
    background: #f6f8f9;
    color: var(--text-soft);
  }

  .top-tabs button.active {
    background: #f2faf8;
    color: var(--brand-strong);
  }

  .top-tabs button.active::after {
    background: var(--brand);
  }

  .top-tabs button:focus-visible {
    outline: 2px solid var(--brand);
    outline-offset: -3px;
  }

  .workspace-content {
    width: 100%;
    max-width: 1440px;
    margin: 0 auto;
    padding: 32px clamp(28px, 4vw, 56px) 56px;
  }

  .page-heading {
    display: grid;
    gap: 4px;
    margin-bottom: 22px;
  }

  .page-heading p,
  .page-heading h1 {
    margin: 0;
  }

  .page-heading p {
    color: var(--brand-strong);
    font-size: 0.68rem;
    font-weight: 800;
    text-transform: uppercase;
  }

  .page-heading h1 {
    font-size: 1.5rem;
    font-weight: 750;
    line-height: 1.25;
  }

  @media (max-width: 760px) {
    .topbar-inner {
      grid-template-columns: minmax(0, 1fr);
      min-height: 0;
      padding: 10px 20px 0;
    }

    .brand-lockup {
      padding-right: 0;
    }

    .top-tabs {
      grid-column: 1 / -1;
      min-height: 44px;
      margin-top: 7px;
    }

    .top-tabs button {
      flex: 1 0 auto;
      min-width: 104px;
      padding: 0 12px;
    }

    .workspace-content {
      padding: 24px 20px 40px;
    }
  }

  @media (max-width: 520px) {
    .topbar-inner {
      padding-inline: 14px;
    }

    .top-tabs button {
      min-width: 98px;
      padding-inline: 10px;
      font-size: 0.78rem;
    }

    .workspace-content {
      padding: 20px 14px 32px;
    }

    .page-heading {
      margin-bottom: 16px;
    }

    .page-heading h1 {
      font-size: 1.35rem;
    }
  }
</style>
