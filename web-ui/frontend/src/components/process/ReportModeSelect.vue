<script setup>
  import { computed, nextTick, ref } from 'vue'
  import { Check, ChevronDown } from 'lucide-vue-next'
  import { useClickOutside } from '../../composables/useClickOutside'

  const props = defineProps({
    modelValue: { type: String, default: 'standard' }
  })
  const emit = defineEmits(['update:modelValue'])
  const modes = [
    { value: 'standard', label: '标准精读', description: '保留解释与推导' },
    { value: 'brief', label: '精简速览', description: '聚焦核心判断与依据' }
  ]
  const selected = computed(
    () => modes.find((mode) => mode.value === props.modelValue) || modes[0]
  )
  const root = ref(null)
  const trigger = ref(null)
  const menu = ref(null)
  const open = ref(false)
  const close = () => {
    open.value = false
  }
  const focusOption = async (index) => {
    open.value = true
    await nextTick()
    menu.value?.querySelectorAll('[role="option"]')[index]?.focus()
  }
  const toggle = () => {
    if (open.value) close()
    else focusOption(modes.indexOf(selected.value))
  }
  const select = (value) => {
    emit('update:modelValue', value)
    close()
    trigger.value?.focus()
  }
  const onKeydown = (event, index) => {
    const positions = {
      ArrowDown: (index + 1) % modes.length,
      ArrowUp: (index + modes.length - 1) % modes.length,
      Home: 0,
      End: modes.length - 1
    }
    if (event.key in positions) {
      event.preventDefault()
      focusOption(positions[event.key])
    } else if (event.key === 'Escape') {
      event.preventDefault()
      close()
      trigger.value?.focus()
    }
  }
  const onFocusout = (event) => {
    if (!root.value?.contains(event.relatedTarget)) close()
  }
  useClickOutside(root, close)
</script>

<template>
  <div ref="root" class="mode-field" @focusout="onFocusout">
    <label id="report-mode-label" for="report-mode">阅读模式</label>
    <div class="mode-dropdown" :class="{ open }">
      <button
        id="report-mode"
        ref="trigger"
        type="button"
        class="preset-select mode-trigger"
        aria-haspopup="listbox"
        :aria-expanded="open"
        :aria-controls="open ? 'report-mode-options' : undefined"
        @click="toggle"
        @keydown.down.prevent="focusOption(0)"
        @keydown.up.prevent="focusOption(modes.length - 1)"
      >
        <span>{{ selected.label }} · {{ selected.description }}</span>
        <ChevronDown :size="16" aria-hidden="true" />
      </button>
      <div
        v-if="open"
        id="report-mode-options"
        ref="menu"
        class="mode-menu"
        role="listbox"
        aria-labelledby="report-mode-label"
      >
        <button
          v-for="(mode, index) in modes"
          :key="mode.value"
          type="button"
          role="option"
          class="mode-option"
          :class="{ active: mode.value === modelValue }"
          :aria-selected="mode.value === modelValue"
          tabindex="-1"
          @click="select(mode.value)"
          @keydown="onKeydown($event, index)"
        >
          <span
            ><strong>{{ mode.label }}</strong
            ><small>{{ mode.description }}</small></span
          >
          <Check
            v-if="mode.value === modelValue"
            :size="16"
            aria-hidden="true"
          />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
  .mode-field {
    display: grid;
    gap: 8px;
    min-width: 0;
  }
  label {
    color: var(--text-soft);
    font-size: 0.88rem;
    font-weight: 700;
  }
  .mode-dropdown {
    position: relative;
  }
  .mode-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    text-align: left;
    cursor: pointer;
  }
  .mode-trigger span {
    min-width: 0;
  }
  .mode-trigger svg {
    flex-shrink: 0;
    color: #64748b;
    transition: transform 0.18s ease;
  }
  .open .mode-trigger svg {
    transform: rotate(180deg);
  }
  .mode-menu {
    position: absolute;
    z-index: 40;
    top: calc(100% + 8px);
    width: 100%;
    padding: 6px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #fff;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.2);
  }
  .mode-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    width: 100%;
    padding: 10px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: #334155;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .mode-option span {
    display: grid;
    gap: 4px;
  }
  .mode-option strong {
    font-size: 0.84rem;
  }
  .mode-option small {
    font-size: 0.78rem;
  }
  .mode-option:hover,
  .mode-option:focus-visible {
    outline: 0;
    background: #f1f5f9;
  }
  .mode-option.active {
    background: var(--brand-soft);
    color: var(--brand-strong);
  }
</style>
