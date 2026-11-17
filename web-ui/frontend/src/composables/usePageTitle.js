import { ref } from 'vue'

// Detail part of the browser tab title (job title, history record, ...),
// set by the active view and combined with the page name in App.vue.
const pageTitleDetail = ref('')

export const setPageTitleDetail = (value) => {
  pageTitleDetail.value = String(value || '').trim()
}

export const usePageTitleDetail = () => pageTitleDetail
