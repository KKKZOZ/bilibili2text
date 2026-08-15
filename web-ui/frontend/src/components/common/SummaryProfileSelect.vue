<script setup>
  import { ChevronDown } from 'lucide-vue-next'
  import InlineNotice from './InlineNotice.vue'
  import { formatSummaryProfileLabel } from '../../composables/useSummaryConfig'

  defineProps({
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
</script>

<template>
  <div class="summary-profile-field" :class="{ compact }">
    <label :for="id">{{ label }}</label>
    <div class="summary-profile-control">
      <select
        :id="id"
        class="preset-select summary-profile-select"
        :value="modelValue"
        :disabled="disabled || loading || profiles.length === 0"
        @change="emit('update:modelValue', $event.target.value)"
      >
        <option v-if="loading" value="">正在加载模型配置...</option>
        <option v-else-if="profiles.length === 0" value="">
          未获取到模型配置（将使用后端默认）
        </option>
        <option
          v-for="profile in profiles"
          :key="profile.name"
          :value="profile.name"
        >
          {{ formatSummaryProfileLabel(profile) }}
        </option>
      </select>
      <ChevronDown :size="16" aria-hidden="true" />
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

  .summary-profile-control {
    position: relative;
  }

  .summary-profile-control svg {
    position: absolute;
    top: 50%;
    right: 14px;
    color: #64748b;
    pointer-events: none;
    transform: translateY(-50%);
  }

  .summary-profile-select {
    appearance: none;
    padding-right: 40px;
  }

  .compact .preset-select {
    min-height: 38px;
    border-radius: 8px;
    padding-left: 12px;
    font-size: 0.84rem;
  }
</style>
