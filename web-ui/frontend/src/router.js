import { createRouter, createWebHashHistory } from 'vue-router'
import ProcessView from './components/ProcessView.vue'
import HistoryView from './components/HistoryView.vue'
import RagView from './components/RagView.vue'
import PublicApiKeyView from './components/PublicApiKeyView.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/process' },
    { path: '/process', component: ProcessView },
    { path: '/process/:jobId', component: ProcessView },
    { path: '/history', component: HistoryView },
    { path: '/rag', component: RagView },
    { path: '/settings', component: PublicApiKeyView }
  ]
})
