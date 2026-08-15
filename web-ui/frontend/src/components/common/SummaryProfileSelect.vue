<script setup>
  import { computed, ref, watch } from 'vue'
  import { ChevronDown } from 'lucide-vue-next'
  import InlineNotice from './InlineNotice.vue'
  import { useClickOutside } from '../../composables/useClickOutside'
  import { formatSummaryProfileLabel } from '../../composables/useSummaryConfig'

  const props = defineProps({
    modelValue: {
      type: String,
      default: ''
    },
    profiles: {
      type: Array,
      default: () => []
    },
    id: {
      type: String,
      default: 'summary-profile-select'
    },
    label: {
      type: String,
      default: '模型配置'
    },
    loading: Boolean,
    disabled: Boolean,
    error: {
      type: String,
      default: ''
    },
    compact: Boolean
  })

  const emit = defineEmits(['update:modelValue', 'retry'])
  const root = ref(null)
  const open = ref(false)

  const selected = computed(
    () =>
      props.profiles.find((profile) => profile.name === props.modelValue) ||
      props.profiles[0] ||
      null
  )

  const close = () => {
    open.value = false
  }
  const toggle = () => {
    if (props.disabled || props.loading || props.profiles.length === 0) return
    open.value = !open.value
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
  <div ref="root" class="summary-profile-field" :class="{ compact }">
    <label :for="id">{{ label }}</label>
    <div class="summary-profile-dropdown" :class="{ open }">
      <button
        :id="id"
        type="button"
        class="preset-select summary-profile-trigger"
        :disabled="disabled || loading || profiles.length === 0"
        aria-haspopup="listbox"
        :aria-expanded="open"
        @click="toggle"
      >
        <span>
          {{
            loading
              ? '正在加载模型配置...'
              : profiles.length === 0
                ? '未获取到模型配置（将使用后端默认）'
                : selected
                  ? formatSummaryProfileLabel(selected)
                  : '请选择模型配置'
          }}
        </span>
        <ChevronDown :size="16" aria-hidden="true" />
      </button>
      <div v-if="open" class="summary-profile-menu" role="listbox">
        <button
          v-for="profile in profiles"
          :key="profile.name"
          type="button"
          class="summary-profile-option"
          :class="{ active: profile.name === modelValue }"
          role="option"
          :aria-selected="profile.name === modelValue"
          @click="select(profile.name)"
        >
          <span>{{ formatSummaryProfileLabel(profile) }}</span>
          <span v-if="profile.name === modelValue" class="current-tag">
            当前
          </span>
        </button>
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
    <p v-else-if="!loading && profiles.length === 0" class="preset-hint">
      暂未连接到后端模型配置接口，提交时会使用服务端默认模型。
    </p>
  </div>
</template>

<style scoped>
  .summary-profile-field {
    display: grid;
    gap: 8px;
    min-width: 0;
  }

  .summary-profile-field > label {
    color: var(--text-soft);
    font-size: 0.88rem;
    font-weight: 700;
  }

  .summary-profile-dropdown {
    position: relative;
  }

  .summary-profile-trigger {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    text-align: left;
    cursor: pointer;
  }

  .summary-profile-trigger > span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .summary-profile-trigger svg {
    flex: 0 0 auto;
    color: #64748b;
    transition: transform 0.18s ease;
  }

  .open .summary-profile-trigger svg {
    transform: rotate(180deg);
  }

  .summary-profile-menu {
    position: absolute;
    z-index: 40;
    top: calc(100% + 8px);
    right: 0;
    width: 100%;
    max-height: 260px;
    overflow-y: auto;
    padding: 6px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #fff;
    box-shadow: 0 18px 40px rgba(15, 23, 42, 0.2);
  }

  .summary-profile-option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    width: 100%;
    min-height: 38px;
    padding: 8px 10px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: #334155;
    font: inherit;
    font-size: 0.84rem;
    text-align: left;
    cursor: pointer;
  }

  .summary-profile-option:hover,
  .summary-profile-option:focus-visible {
    outline: 0;
    background: #f1f5f9;
  }

  .summary-profile-option.active {
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-weight: 700;
  }

  .summary-profile-option > span:first-child {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .current-tag {
    flex: 0 0 auto;
    color: var(--brand-strong);
    font-size: 0.72rem;
    font-weight: 700;
  }

  .compact .preset-select {
    min-height: 38px;
    border-radius: 6px;
    padding-left: 12px;
    font-size: 0.84rem;
  }
</style>
