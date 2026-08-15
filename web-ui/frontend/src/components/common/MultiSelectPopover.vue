<script setup>
  import { ref } from 'vue'
  import { ChevronDown } from 'lucide-vue-next'
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
  const open = ref(false)
  const hasMore = ref(false)

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
    if (open.value) requestAnimationFrame(updateScrollHint)
  }
  const close = () => {
    open.value = false
  }
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
  <div ref="root" class="multi-select" :class="{ compact }">
    <span v-if="label" class="multi-select-label">{{ label }}</span>
    <button
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
      <div
        ref="menu"
        class="multi-select-menu"
        :class="{ 'has-more': hasMore }"
        role="group"
        :aria-label="label || triggerLabel"
        @scroll="updateScrollHint"
      >
        <label
          v-for="option in options"
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
        <span v-if="options.length === 0" class="multi-select-empty">
          {{ emptyText }}
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
    color: #64748b;
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
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #334155;
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
    color: #64748b;
    transition: transform 0.15s ease;
  }

  .multi-select-trigger[aria-expanded='true'] > svg:last-child {
    transform: rotate(180deg);
  }

  .multi-select-trigger:hover:not(:disabled),
  .multi-select-trigger.active {
    border-color: #94a3b8;
  }

  .multi-select-trigger:focus-visible {
    border-color: #14b8a6;
    outline: 3px solid rgba(20, 184, 166, 0.14);
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
  }

  .multi-select-menu {
    width: 100%;
    max-height: 280px;
    overflow-y: auto;
    padding: 5px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16);
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
    border-radius: 4px;
    color: #334155;
    font-size: 0.8rem;
    cursor: pointer;
  }

  .multi-select-option:hover {
    background: #f1f5f9;
  }

  .multi-select-option input {
    accent-color: #0d9488;
  }

  .option-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .option-count {
    color: #94a3b8;
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
    color: #94a3b8;
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
    background: linear-gradient(to bottom, transparent, #fff 48%);
    color: #64748b;
    font-size: 0.7rem;
    pointer-events: none;
  }

  .compact {
    display: block;
  }

  .compact .multi-select-trigger {
    width: auto;
    height: 38px;
    border-color: rgba(148, 163, 184, 0.35);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.8);
    font-size: 0.78rem;
  }

  .compact .multi-select-shell {
    top: calc(100% + 8px);
  }

  .multi-select-clear {
    width: 100%;
    padding: 7px;
    border: none;
    border-top: 1px solid #e2e8f0;
    background: transparent;
    color: var(--brand-strong);
    font-size: 0.76rem;
    cursor: pointer;
  }
</style>
