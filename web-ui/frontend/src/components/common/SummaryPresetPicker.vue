<script setup>
  import { computed, ref, watch } from 'vue'
  import { ChevronDown } from 'lucide-vue-next'
  import InlineNotice from './InlineNotice.vue'
  import { useClickOutside } from '../../composables/useClickOutside'

  const props = defineProps({
    modelValue: {
      type: String,
      default: ''
    },
    presets: {
      type: Array,
      default: () => []
    },
    id: {
      type: String,
      default: 'summary-preset-select'
    },
    label: {
      type: String,
      default: '总结模板'
    },
    loading: Boolean,
    disabled: Boolean,
    error: {
      type: String,
      default: ''
    },
    preview: Boolean,
    customPromptTemplate: {
      type: String,
      default: ''
    },
    fallbackPromptTemplate: {
      type: String,
      default: ''
    },
    customPresetValue: {
      type: String,
      default: '__user_custom__'
    },
    compact: Boolean
  })

  const emit = defineEmits(['update:modelValue', 'retry'])
  const root = ref(null)
  const open = ref(false)
  const previewedName = ref('')

  const selected = computed(
    () =>
      props.presets.find((item) => item.name === props.modelValue) ||
      props.presets[0] ||
      null
  )
  const previewed = computed(
    () =>
      props.presets.find((item) => item.name === previewedName.value) ||
      selected.value
  )
  const previewText = computed(() => {
    const preset = previewed.value
    const template =
      preset?.name === props.customPresetValue
        ? props.customPromptTemplate || props.fallbackPromptTemplate
        : preset?.prompt_template
    const normalized = String(template || '')
      .replace(/\r\n/g, '\n')
      .split('\n')
      .map((line) => line.replace(/[^\S\n]+/g, ' ').trim())
      .join('\n')
      .trim()
    return normalized || '此模板暂无可预览内容。'
  })

  const close = () => {
    open.value = false
    previewedName.value = ''
  }
  const toggle = () => {
    if (props.disabled || props.loading || props.presets.length === 0) return
    open.value = !open.value
    previewedName.value = props.modelValue
  }
  const select = (name) => {
    emit('update:modelValue', name)
    close()
  }

  useClickOutside(root, close)
  watch(
    () => props.disabled,
    (disabled) => disabled && close()
  )
</script>

<template>
  <div ref="root" class="summary-preset-field" :class="{ compact }">
    <label :for="id">{{ label }}</label>
    <div v-if="!preview" class="summary-preset-control">
      <select
        :id="id"
        class="preset-select summary-preset-native"
        :value="modelValue"
        :disabled="disabled || loading || presets.length === 0"
        @change="emit('update:modelValue', $event.target.value)"
      >
        <option v-if="loading" value="">正在加载模板...</option>
        <option v-else-if="presets.length === 0" value="">
          未获取到模板（将使用后端默认）
        </option>
        <option
          v-for="preset in presets"
          :key="preset.name"
          :value="preset.name"
        >
          {{ preset.label }}
        </option>
      </select>
      <ChevronDown :size="16" aria-hidden="true" />
    </div>
    <div v-else class="summary-preset-dropdown" :class="{ open }">
      <button
        :id="id"
        type="button"
        class="preset-select summary-preset-trigger"
        :disabled="disabled || loading || presets.length === 0"
        aria-haspopup="listbox"
        :aria-expanded="open"
        @click="toggle"
      >
        <span>
          {{
            loading
              ? '正在加载模板...'
              : presets.length === 0
                ? '未获取到模板（将使用后端默认）'
                : selected?.label || '请选择总结模板'
          }}
        </span>
        <ChevronDown :size="16" aria-hidden="true" />
      </button>
      <div v-if="open" class="summary-preset-popover">
        <div class="summary-preset-option-list" role="listbox">
          <button
            v-for="preset in presets"
            :key="preset.name"
            type="button"
            class="summary-preset-option"
            :class="{
              active: preset.name === modelValue,
              previewing: preset.name === previewed?.name
            }"
            @mouseenter="previewedName = preset.name"
            @focus="previewedName = preset.name"
            @click="select(preset.name)"
          >
            <span>{{ preset.label }}</span>
            <span v-if="preset.name === modelValue" class="current-tag">
              当前
            </span>
          </button>
        </div>
        <div class="summary-preset-preview">
          <p>模板预览</p>
          <h4>{{ previewed?.label || '总结模板' }}</h4>
          <div>{{ previewText }}</div>
        </div>
      </div>
    </div>
    <InlineNotice v-if="error" kind="error" compact>
      {{ error }}
      <template #action>
        <button class="preset-retry" type="button" @click="emit('retry')">
          重试
        </button>
      </template>
    </InlineNotice>
    <p v-else-if="!loading && presets.length === 0" class="preset-hint">
      暂未连接到后端模板接口，提交时会使用服务端默认模板。
    </p>
  </div>
</template>

<style scoped>
  .summary-preset-field {
    display: grid;
    gap: 8px;
    min-width: 0;
  }

  .summary-preset-field > label {
    color: var(--text-soft);
    font-size: 0.88rem;
    font-weight: 700;
  }

  .summary-preset-dropdown {
    position: relative;
  }

  .summary-preset-control {
    position: relative;
  }

  .summary-preset-control svg {
    position: absolute;
    top: 50%;
    right: 14px;
    color: #64748b;
    pointer-events: none;
    transform: translateY(-50%);
  }

  .summary-preset-native {
    appearance: none;
    padding-right: 40px;
  }

  .summary-preset-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    text-align: left;
    cursor: pointer;
  }

  .summary-preset-trigger > span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .summary-preset-trigger svg {
    flex: 0 0 auto;
    transition: transform 0.18s ease;
  }

  .open .summary-preset-trigger svg {
    transform: rotate(180deg);
  }

  .summary-preset-popover {
    position: absolute;
    z-index: 40;
    top: calc(100% + 8px);
    right: 0;
    display: grid;
    grid-template-columns: minmax(160px, 0.8fr) minmax(240px, 1.2fr);
    width: min(620px, calc(100vw - 48px));
    overflow: hidden;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #fff;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.2);
  }

  .summary-preset-option-list {
    max-height: 320px;
    overflow-y: auto;
    padding: 7px;
    border-right: 1px solid #e2e8f0;
    background: #f8fafc;
  }

  .summary-preset-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    width: 100%;
    padding: 9px 10px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: #334155;
    font: inherit;
    font-size: 0.82rem;
    cursor: pointer;
    text-align: left;
  }

  .summary-preset-option:hover,
  .summary-preset-option.previewing {
    background: #fff;
    border-color: #cbd5e1;
  }

  .summary-preset-option.active {
    color: var(--brand-strong);
    font-weight: 700;
  }

  .current-tag {
    padding: 2px 5px;
    border-radius: 4px;
    background: var(--brand-soft);
    font-size: 0.68rem;
  }

  .summary-preset-preview {
    min-width: 0;
    padding: 16px;
  }

  .summary-preset-preview p {
    margin: 0 0 5px;
    color: #64748b;
    font-size: 0.68rem;
    font-weight: 800;
  }

  .summary-preset-preview h4 {
    margin: 0 0 10px;
    font-size: 0.94rem;
  }

  .summary-preset-preview div {
    max-height: 250px;
    overflow-y: auto;
    color: #475569;
    font-size: 0.78rem;
    line-height: 1.55;
    white-space: pre-wrap;
  }

  .compact .preset-select {
    min-height: 38px;
    border-radius: 6px;
    padding: 0 12px;
    font-size: 0.84rem;
  }

  @media (max-width: 720px) {
    .summary-preset-popover {
      right: auto;
      left: 0;
      grid-template-columns: 1fr;
    }

    .summary-preset-option-list {
      max-height: 190px;
      border-right: none;
      border-bottom: 1px solid #e2e8f0;
    }

    .summary-preset-preview {
      display: none;
    }
  }
</style>
