<script setup>
  import { computed, onBeforeUnmount, onMounted, watch, watchEffect } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import {
    AudioLines,
    Brain,
    Github,
    History,
    KeyRound,
    Sparkles
  } from 'lucide-vue-next'
  import {
    startJobStore,
    stopJobStore,
    useJobStore
  } from './composables/useJobStore'
  import { usePageTitleDetail } from './composables/usePageTitle'
  import { usePublicCredentials } from './composables/usePublicCredentials'
  import { useRuntimeFeatures } from './composables/useRuntimeFeatures'
  import { useSummaryConfig } from './composables/useSummaryConfig'

  const route = useRoute()
  const router = useRouter()
  const { isOpenPublic, loadRuntimeFeatures } = useRuntimeFeatures()
  const { refreshCredentials } = usePublicCredentials()
  const { initializeSummaryConfig } = useSummaryConfig()
  const { activeJobs } = useJobStore()
  const pageTitleDetail = usePageTitleDetail()

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

  const pageHeading = computed(() =>
    currentView.value === 'process' && route.params.jobId
      ? '任务详情'
      : currentPage.value.label
  )

  const contentStyle = computed(() =>
    route.meta.contentWidth ? { '--content-max': route.meta.contentWidth } : {}
  )

  watchEffect(() => {
    if (route.meta.standalone) return
    document.title = [
      pageTitleDetail.value,
      pageHeading.value,
      'bilibili-to-text'
    ]
      .filter(Boolean)
      .join(' · ')
  })

  onMounted(() => {
    if (route.meta.standalone) return
    startJobStore()
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
    stopJobStore()
  })

  watch(isOpenPublic, (openPublic) => {
    if (!openPublic && route.path === '/settings') router.push('/process')
  })
</script>

<template>
  <RouterView v-if="route.meta.standalone" />
  <div v-else class="app-shell">
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
          <RouterLink
            v-for="item in navigation"
            :key="item.key"
            :to="item.path"
            :class="{ active: currentView === item.key }"
            :aria-current="currentView === item.key ? 'page' : undefined"
          >
            <component :is="item.icon" :size="17" aria-hidden="true" />
            <span>{{ item.label }}</span>
            <span
              v-if="item.key === 'history' && activeJobs.length"
              class="tab-badge"
              :title="`${activeJobs.length} 个任务进行中`"
            >
              {{ activeJobs.length }}
              <span class="sr-only">个任务进行中</span>
            </span>
          </RouterLink>
        </nav>

        <a
          class="github-link"
          href="https://github.com/KKKZOZ/bilibili2text"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="在 GitHub 查看 bilibili2text"
          title="GitHub"
        >
          <Github :size="21" aria-hidden="true" />
        </a>
      </div>
    </header>

    <main class="workspace-content" :style="contentStyle">
      <header class="page-heading">
        <h1>{{ pageHeading }}</h1>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
  .app-shell {
    --page-gutter: clamp(28px, 4vw, 56px);
    --page-max: 1220px;
    min-height: 100vh;
  }

  .topbar {
    position: sticky;
    z-index: 100;
    top: 0;
    border-bottom: 1px solid var(--line);
    background: color-mix(in srgb, var(--panel-bg) 96%, transparent);
    backdrop-filter: blur(12px);
  }

  .topbar-inner {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    width: 100%;
    max-width: calc(var(--page-max) + 2 * var(--page-gutter));
    min-height: 64px;
    margin: 0 auto;
    padding: 0 var(--page-gutter);
  }

  .brand-lockup {
    display: flex;
    align-items: center;
    gap: 10px;
    padding-right: 30px;
    border-radius: var(--radius-lg);
    color: var(--text-main);
    text-decoration: none;
  }

  .brand-lockup:focus-visible {
    outline: 0;
    box-shadow: 0 0 0 3px var(--focus-ring);
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

  .top-tabs a {
    position: relative;
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    gap: 7px;
    min-width: 110px;
    padding: 0 16px;
    color: var(--text-muted);
    font-size: 0.82rem;
    font-weight: 700;
    text-decoration: none;
  }

  .tab-badge {
    display: inline-grid;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    place-items: center;
    border-radius: var(--radius-pill);
    background: var(--brand-solid);
    color: var(--on-solid);
    font-size: 0.68rem;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }

  .top-tabs a::after {
    position: absolute;
    right: 14px;
    bottom: 0;
    left: 14px;
    height: 2px;
    background: transparent;
    content: '';
  }

  .top-tabs a:hover {
    background: var(--surface-subtle);
    color: var(--text-soft);
  }

  .top-tabs a.active {
    background: var(--brand-soft);
    color: var(--brand-strong);
  }

  .top-tabs a.active::after {
    background: var(--brand);
  }

  .top-tabs a:focus-visible {
    outline: 2px solid var(--brand);
    outline-offset: -3px;
  }

  .github-link {
    display: grid;
    width: 38px;
    height: 38px;
    margin-left: 16px;
    place-items: center;
    border-radius: var(--radius-lg);
    color: var(--text-soft);
    transition:
      background-color 0.15s ease,
      color 0.15s ease;
  }

  .github-link:hover {
    background: var(--surface-muted);
    color: var(--text-main);
  }

  .github-link:focus-visible {
    outline: 2px solid var(--brand);
    outline-offset: 2px;
  }

  .workspace-content {
    width: 100%;
    max-width: calc(var(--page-max) + 2 * var(--page-gutter));
    margin: 0 auto;
    padding: 32px var(--page-gutter) 56px;
  }

  .page-heading {
    display: grid;
    gap: 4px;
    max-width: var(--content-max, none);
    margin: 0 auto 22px;
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
    font-weight: 700;
    line-height: 1.25;
  }

  @media (max-width: 760px) {
    .app-shell {
      --page-gutter: 20px;
    }

    .topbar-inner {
      grid-template-columns: minmax(0, 1fr) auto;
      min-height: 0;
      padding-top: 10px;
    }

    .brand-lockup {
      padding-right: 0;
    }

    .top-tabs {
      grid-column: 1 / -1;
      grid-row: 2;
      min-height: 44px;
      margin-top: 7px;
    }

    .github-link {
      grid-column: 2;
      grid-row: 1;
      margin-left: 12px;
    }

    .top-tabs a {
      flex: 1 0 auto;
      min-width: 104px;
      padding: 0 12px;
    }

    .workspace-content {
      padding-top: 24px;
      padding-bottom: 40px;
    }
  }

  @media (max-width: 520px) {
    .app-shell {
      --page-gutter: 14px;
    }

    .top-tabs a {
      min-width: 98px;
      padding-inline: 10px;
      font-size: 0.78rem;
    }

    .workspace-content {
      padding-top: 20px;
      padding-bottom: 32px;
    }

    .page-heading {
      margin-bottom: 16px;
    }

    .page-heading h1 {
      font-size: 1.35rem;
    }
  }
</style>
