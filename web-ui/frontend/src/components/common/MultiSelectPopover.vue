<script setup>
  import { computed, nextTick, ref, watch } from 'vue'
  import { ChevronDown, Search } from 'lucide-vue-next'
  import { useClickOutside } from '../../composables/useClickOutside'

  const props = defineProps({
    modelValue: {
      type: Array,
      default: () => []
    },
    options: {
      type: Array,
      default: () => []
    },
    label: {
      type: String,
      default: ''
    },
    triggerLabel: {
      type: String,
      required: true
    },
    emptyText: {
      type: String,
      default: '暂无选项'
    },
    disabled: Boolean,
    compact: Boolean
  })

  const emit = defineEmits(['update:modelValue'])
  const root = ref(null)
  const menu = ref(null)
  const trigger = ref(null)
  const searchInput = ref(null)
  const open = ref(false)
  const hasMore = ref(false)
  const query = ref('')

  // Long lists (authors, categories) get a search box.
  const SEARCH_THRESHOLD = 8
  const searchable = computed(() => props.options.length > SEARCH_THRESHOLD)
  const visibleOptions = computed(() => {
    const keyword = query.value.trim().toLowerCase()
    if (!keyword) return props.options
    return props.options.filter((option) =>
      String(option.label || '')
        .toLowerCase()
        .includes(keyword)
    )
  })

  const updateScrollHint = () => {
    const element = menu.value
    hasMore.value = Boolean(
      element &&
      element.scrollHeight - element.scrollTop - element.clientHeight > 4
    )
  }

  const toggleOpen = () => {
    if (props.disabled) return
    open.value = !open.value
    if (!open.value) return
    query.value = ''
    void nextTick(() => {
      updateScrollHint()
      searchInput.value?.focus()
    })
  }
  const close = () => {
    open.value = false
  }
  const onKeydown = (event) => {
    if (event.key !== 'Escape' || !open.value) return
    event.stopPropagation()
    close()
    trigger.value?.focus()
  }

  watch(query, () => void nextTick(updateScrollHint))
  const toggleOption = (value, checked) => {
    emit(
      'update:modelValue',
      checked
        ? [...props.modelValue, value]
        : props.modelValue.filter((item) => item !== value)
    )
  }

  useClickOutside(root, close)
</script>

<template>
  <div
    ref="root"
    class="multi-select"
    :class="{ compact }"
    @keydown="onKeydown"
  >
    <span v-if="label" class="multi-select-label">{{ label }}</span>
    <button
      ref="trigger"
      type="button"
      class="multi-select-trigger"
      :class="{ active: modelValue.length > 0 }"
      :disabled="disabled"
      :aria-expanded="open"
      @click="toggleOpen"
    >
      <slot name="icon"></slot>
      <span>{{ triggerLabel }}</span>
      <ChevronDown :size="compact ? 13 : 15" />
    </button>
    <div v-if="open" class="multi-select-shell">
      <div v-if="searchable" class="multi-select-search">
        <Search :size="13" aria-hidden="true" />
        <input
          ref="searchInput"
          v-model="query"
          type="search"
          :aria-label="`搜索${label || '选项'}`"
          placeholder="搜索..."
        />
      </div>
      <div
        ref="menu"
        class="multi-select-menu"
        :class="{ 'has-more': hasMore, 'with-search': searchable }"
        role="group"
        :aria-label="label || triggerLabel"
        @scroll="updateScrollHint"
      >
        <label
          v-for="option in visibleOptions"
          :key="option.value"
          class="multi-select-option"
          :class="option.kind ? `option-${option.kind}` : ''"
        >
          <input
            type="checkbox"
            :checked="modelValue.includes(option.value)"
            @change="toggleOption(option.value, $event.target.checked)"
          />
          <span class="option-label">{{ option.label }}</span>
          <span v-if="option.count != null" class="option-count">
            {{ option.count }}
          </span>
        </label>
        <span v-if="visibleOptions.length === 0" class="multi-select-empty">
          {{ options.length === 0 ? emptyText : '没有匹配的选项' }}
        </span>
        <button
          v-if="compact && modelValue.length > 0"
          type="button"
          class="multi-select-clear"
          @click="emit('update:modelValue', [])"
        >
          清除筛选
        </button>
      </div>
      <div v-if="hasMore" class="multi-select-scroll-hint">
        <span>向下滚动查看更多</span>
        <ChevronDown :size="14" />
      </div>
    </div>
  </div>
</template>

<style scoped>
  .multi-select {
    position: relative;
    display: grid;
    gap: 5px;
    min-width: 0;
  }

  .multi-select-label {
    color: var(--text-muted);
    font-size: 0.72rem;
    font-weight: 700;
  }

  .multi-select-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    min-width: 0;
    height: 36px;
    padding: 0 9px 0 10px;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-md);
    background: var(--panel-bg);
    color: var(--text-soft);
    font: inherit;
    font-size: 0.82rem;
    cursor: pointer;
    text-align: left;
  }

  .multi-select-trigger > span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .multi-select-trigger > svg:last-child {
    flex: 0 0 auto;
    color: var(--text-muted);
    transition: transform 0.15s ease;
  }

  .multi-select-trigger[aria-expanded='true'] > svg:last-child {
    transform: rotate(180deg);
  }

  .multi-select-trigger:hover:not(:disabled),
  .multi-select-trigger.active {
    border-color: var(--text-faint);
  }

  .multi-select-trigger:focus-visible {
    border-color: var(--brand);
    outline: 3px solid var(--focus-ring);
  }

  .multi-select-trigger:disabled {
    cursor: wait;
    opacity: 0.65;
  }

  .multi-select-shell {
    position: absolute;
    z-index: 30;
    top: calc(100% + 6px);
    left: 0;
    width: max(100%, 220px);
    max-width: min(320px, calc(100vw - 40px));
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-pop);
  }

  .multi-select-menu {
    width: 100%;
    max-height: 280px;
    overflow-y: auto;
    padding: 5px;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-md);
    background: var(--panel-bg);
  }

  .multi-select-search {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 36px;
    padding: 0 10px;
    border: 1px solid var(--line-strong);
    border-bottom: 0;
    border-radius: var(--radius-md) var(--radius-md) 0 0;
    background: var(--panel-bg);
    color: var(--text-muted);
  }

  .multi-select-search input {
    flex: 1;
    min-width: 0;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--text-main);
    font: inherit;
    font-size: 0.8rem;
    appearance: none;
  }

  .multi-select-search input::-webkit-search-cancel-button {
    display: none;
  }

  .multi-select-menu.with-search {
    border-radius: 0 0 var(--radius-md) var(--radius-md);
  }

  .multi-select-menu.has-more {
    padding-bottom: 38px;
  }

  .multi-select-option {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
    min-height: 34px;
    padding: 5px 7px;
    border-radius: var(--radius-sm);
    color: var(--text-soft);
    font-size: 0.8rem;
    cursor: pointer;
  }

  .multi-select-option:hover {
    background: var(--surface-muted);
  }

  .multi-select-option input {
    accent-color: var(--brand);
  }

  .option-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .option-count {
    color: var(--text-faint);
    font-size: 0.72rem;
  }

  .option-child {
    padding-left: 24px;
  }

  .option-parent {
    font-weight: 700;
  }

  .multi-select-empty {
    display: block;
    padding: 12px 8px;
    color: var(--text-faint);
    font-size: 0.8rem;
    text-align: center;
  }

  .multi-select-scroll-hint {
    position: absolute;
    right: 1px;
    bottom: 1px;
    left: 1px;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    gap: 3px;
    height: 45px;
    padding-bottom: 7px;
    border-radius: 0 0 5px 5px;
    background: linear-gradient(to bottom, transparent, var(--panel-bg) 48%);
    color: var(--text-muted);
    font-size: 0.7rem;
    pointer-events: none;
  }

  .compact {
    display: block;
  }

  .compact .multi-select-trigger {
    width: auto;
    height: 38px;
    border-color: var(--line-strong);
    border-radius: var(--radius-lg);
    background: var(--panel-bg);
    font-size: 0.78rem;
  }

  .compact .multi-select-shell {
    top: calc(100% + 8px);
  }

  .multi-select-clear {
    width: 100%;
    padding: 7px;
    border: none;
    border-top: 1px solid var(--line);
    background: transparent;
    color: var(--brand-strong);
    font-size: 0.76rem;
    cursor: pointer;
  }
</style>
