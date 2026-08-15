<script setup>
  import {
    ChevronLeft,
    ChevronRight,
    ChevronsLeft,
    ChevronsRight
  } from 'lucide-vue-next'
  import { ref } from 'vue'

  defineProps({
    page: { type: Number, required: true },
    totalPages: { type: Number, required: true },
    hasMore: Boolean,
    loading: Boolean
  })

  const emit = defineEmits(['go'])
  const jumpPage = ref('')
  const go = (page) => {
    emit('go', page)
    jumpPage.value = ''
  }
</script>

<template>
  <div class="history-pagination">
    <button :disabled="page <= 1 || loading" title="第一页" @click="go(1)">
      <ChevronsLeft :size="16" />
    </button>
    <button
      :disabled="page <= 1 || loading"
      title="上一页"
      @click="go(page - 1)"
    >
      <ChevronLeft :size="16" />
    </button>
    <span>第 {{ page }} 页 / 共 {{ totalPages }} 页</span>
    <form @submit.prevent="go(jumpPage)">
      <input
        v-model="jumpPage"
        type="number"
        min="1"
        :max="totalPages"
        placeholder="页码"
        :disabled="loading"
      />
      <button type="submit" :disabled="loading || !jumpPage">跳转</button>
    </form>
    <button
      :disabled="!hasMore || loading"
      title="下一页"
      @click="go(page + 1)"
    >
      <ChevronRight :size="16" />
    </button>
    <button
      :disabled="!hasMore || loading"
      title="最后一页"
      @click="go(totalPages)"
    >
      <ChevronsRight :size="16" />
    </button>
  </div>
</template>

<style scoped>
  .history-pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    margin-top: 20px;
  }

  button,
  input {
    height: 34px;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
    color: var(--text-soft);
  }

  button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 34px;
    padding: 0 9px;
    cursor: pointer;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  span {
    color: var(--text-muted);
    font-size: 0.82rem;
    white-space: nowrap;
  }

  form {
    display: inline-flex;
    gap: 5px;
  }

  input {
    width: 64px;
    padding: 0 8px;
  }

  @media (max-width: 640px) {
    .history-pagination {
      flex-wrap: wrap;
    }

    span {
      order: -1;
      width: 100%;
      text-align: center;
    }
  }
</style>
