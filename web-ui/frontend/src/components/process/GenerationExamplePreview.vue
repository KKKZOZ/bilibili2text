<script setup>
  import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
  import { Eye, X } from 'lucide-vue-next'
  import summaryUrl from '../../assets/examples/BV1Q6h16hEv7_summary.html?url'
  import reportUrl from '../../assets/examples/BV1Q6h16hEv7_reading_report.html?url'

  const props = defineProps({ kind: { type: String, required: true } })
  const examples = {
    summary: {
      label: '总结示例',
      description: '按主题整理要点、数据和时间线，方便快速回顾、复制和编辑。',
      url: summaryUrl
    },
    report: {
      label: '阅读报告示例',
      description:
        '将完整转录组织成有排版的文章，展开解释和对比，适合精读与分享。',
      url: reportUrl
    }
  }
  const activeKind = ref(props.kind)
  const example = computed(() => examples[activeKind.value])
  const dialog = ref(null)
  const open = ref(false)
  let previousOverflow = ''
  const show = () => {
    activeKind.value = props.kind
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    open.value = true
    dialog.value.showModal()
  }
  const closed = () => {
    if (!open.value) return
    open.value = false
    document.body.style.overflow = previousOverflow
  }
  const onTabKeydown = async (event) => {
    const keys = Object.keys(examples)
    let index = keys.indexOf(activeKind.value)
    if (event.key === 'ArrowRight') index = (index + 1) % keys.length
    else if (event.key === 'ArrowLeft')
      index = (index - 1 + keys.length) % keys.length
    else if (event.key === 'Home') index = 0
    else if (event.key === 'End') index = keys.length - 1
    else return
    event.preventDefault()
    activeKind.value = keys[index]
    await nextTick()
    dialog.value.querySelector('[role="tab"][aria-selected="true"]').focus()
  }
  onBeforeUnmount(closed)
</script>

<template>
  <button
    class="example-trigger"
    type="button"
    :title="examples[kind].description"
    :aria-label="`查看${examples[kind].label}`"
    aria-haspopup="dialog"
    @click="show"
  >
    <Eye :size="15" aria-hidden="true" />
    查看示例
  </button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="example-dialog"
      :aria-label="example.label"
      @close="closed"
      @click="$event.target === dialog && dialog.close()"
    >
      <div class="example-shell">
        <header class="example-header">
          <div>
            <h2>看看生成效果</h2>
          </div>
          <button
            class="example-close"
            type="button"
            aria-label="关闭示例预览"
            autofocus
            @click="dialog.close()"
          >
            <X :size="22" />
          </button>
        </header>
        <div class="example-options">
          <div class="example-tabs" role="tablist" aria-label="选择示例类型">
            <button
              v-for="(entry, key) in examples"
              :key="key"
              type="button"
              role="tab"
              :id="`example-${kind}-${key}-tab`"
              :aria-controls="`example-${kind}-panel`"
              :aria-selected="activeKind === key"
              :tabindex="activeKind === key ? 0 : -1"
              @keydown="onTabKeydown"
              @click="activeKind = key"
            >
              {{ entry.label }}
            </button>
          </div>
          <p>{{ example.description }}</p>
        </div>
        <div
          v-if="open"
          :id="`example-${kind}-panel`"
          class="example-panel"
          role="tabpanel"
          :aria-labelledby="`example-${kind}-${activeKind}-tab`"
        >
          <iframe
            :key="activeKind"
            :src="example.url"
            :title="example.label"
            sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
            referrerpolicy="no-referrer"
          />
        </div>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
  .example-trigger {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 8px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--brand-strong);
    font-size: 0.8rem;
    cursor: pointer;
    white-space: nowrap;
  }
  .example-trigger:hover {
    background: #edf7f5;
  }
  .example-dialog {
    width: min(1100px, calc(100vw - 48px));
    max-width: none;
    height: min(900px, calc(100dvh - 48px));
    max-height: none;
    margin: auto;
    padding: 0;
    border: 1px solid #dbe1e8;
    border-radius: 12px;
    background: #fff;
    color: #334155;
    box-shadow: 0 24px 80px #0f172a40;
  }
  .example-dialog::backdrop {
    background: #0f172a99;
  }
  .example-shell {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .example-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 18px 24px 12px;
  }
  .example-header h2 {
    margin: 0 0 4px;
    font-size: 1.1rem;
  }
  .example-options p {
    margin: 0;
    font-size: 0.82rem;
    line-height: 1.6;
  }
  .example-close {
    display: grid;
    place-items: center;
    flex-shrink: 0;
    width: 36px;
    height: 36px;
    border: 0;
    border-radius: 6px;
    background: #f1f5f9;
    cursor: pointer;
    color: #475569;
  }
  .example-options {
    display: grid;
    gap: 8px;
    padding: 0 24px 16px;
    border-bottom: 1px solid #e2e8f0;
  }

  .example-tabs {
    display: flex;
    gap: 24px;
    margin-bottom: 4px;
    border-bottom: 1px solid #e2e8f0;
  }
  .example-tabs button {
    position: relative;
    padding: 12px 2px;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: #64748b;
    font: inherit;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: color 0.15s ease;
  }
  .example-tabs button:hover {
    color: #0b6f65;
  }
  .example-tabs button[aria-selected='true'] {
    color: #0b6f65;
  }
  .example-tabs button[aria-selected='true']::after {
    content: '';
    position: absolute;
    right: 0;
    bottom: -1px;
    left: 0;
    height: 3px;
    border-radius: 3px 3px 0 0;
    background: #0f8f83;
  }
  button:focus-visible {
    outline: 2px solid #0f8f83;
    outline-offset: 3px;
  }
  .example-panel {
    flex: 1;
    min-height: 0;
    display: flex;
  }
  iframe {
    flex: 1;
    width: 100%;
    min-height: 0;
    border: 0;
    background: #f2f5f7;
  }
  @media (max-width: 640px) {
    .example-dialog {
      width: 100vw;
      height: 100dvh;
      border: 0;
      border-radius: 0;
    }
    .example-header {
      padding: 14px 16px 10px;
    }
    .example-options {
      padding: 0 16px 12px;
    }
  }
</style>
