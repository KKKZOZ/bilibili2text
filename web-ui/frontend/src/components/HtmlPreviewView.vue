<script setup>
  import { computed } from 'vue'
  import { useRoute } from 'vue-router'
  import { artifactApi } from '../api'

  const route = useRoute()
  const sourceUrl = computed(() =>
    artifactApi.renderedPreviewSourceUrl(
      route.params.downloadId,
      route.query.source_variant === 'summary_no_table'
        ? 'summary_no_table'
        : ''
    )
  )
</script>

<template>
  <iframe
    :key="sourceUrl"
    class="html-preview"
    :src="sourceUrl"
    title="HTML 文档预览"
    sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
    referrerpolicy="no-referrer"
  />
</template>

<style scoped>
  .html-preview {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100%;
    border: 0;
    background: #f2f5f7;
  }
</style>
