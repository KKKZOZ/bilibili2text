<script setup>
  import { LoaderCircle } from 'lucide-vue-next'
  import InlineNotice from '../common/InlineNotice.vue'
  import SummaryPresetPicker from '../common/SummaryPresetPicker.vue'
  import SummaryProfileSelect from '../common/SummaryProfileSelect.vue'

  defineProps({
    selectedProfile: { type: String, default: '' },
    selectedPreset: { type: String, default: '' },
    profiles: { type: Array, default: () => [] },
    presets: { type: Array, default: () => [] },
    loading: Boolean,
    requiresApiKey: Boolean,
    duplicate: Boolean,
    error: { type: String, default: '' },
    success: { type: String, default: '' }
  })

  const emit = defineEmits([
    'update:selectedProfile',
    'update:selectedPreset',
    'regenerate'
  ])
</script>

<template>
  <div class="history-regenerate">
    <div class="history-regenerate-head">
      <p>重新生成配置</p>
      <h3>总结参数</h3>
      <p>
        可切换模型配置与 preset，对同一条历史转录重新生成总结。
        <template v-if="requiresApiKey">
          选择“用户自定义”时，会使用你在 API Key 页面保存的模板。
        </template>
      </p>
    </div>
    <div class="history-regenerate-grid">
      <SummaryProfileSelect
        id="history-summary-profile-select"
        :model-value="selectedProfile"
        :profiles="profiles"
        :disabled="loading"
        compact
        @update:model-value="emit('update:selectedProfile', $event)"
      />
      <SummaryPresetPicker
        id="history-summary-preset-select"
        :model-value="selectedPreset"
        :presets="presets"
        :disabled="loading"
        compact
        @update:model-value="emit('update:selectedPreset', $event)"
      />
    </div>
    <button
      class="submit regenerate-button"
      type="button"
      :disabled="loading"
      @click="emit('regenerate')"
    >
      <LoaderCircle v-if="loading" :size="16" class="spin" />
      <span>{{ loading ? '生成中...' : '用当前配置重新生成总结' }}</span>
    </button>
    <p v-if="duplicate" class="duplicate-hint">
      该模型配置与总结模板已经生成过；重新生成前将要求确认并覆盖原结果。
    </p>
    <InlineNotice v-if="error">{{ error }}</InlineNotice>
    <InlineNotice v-if="success" kind="success">{{ success }}</InlineNotice>
  </div>
</template>

<style scoped>
  .history-regenerate {
    display: grid;
    gap: 16px;
    margin: 20px 0;
    padding: 18px;
    border: 1px solid #dbeafe;
    border-radius: 8px;
    background: rgba(239, 246, 255, 0.55);
  }

  .history-regenerate-head {
    display: grid;
    gap: 5px;
  }

  .history-regenerate-head p,
  .history-regenerate-head h3 {
    margin: 0;
  }

  .history-regenerate-head > p:first-child {
    color: #0284c7;
    font-size: 0.72rem;
    font-weight: 800;
    text-transform: uppercase;
  }

  .history-regenerate-head h3 {
    font-size: 1rem;
  }

  .history-regenerate-head > p:last-child,
  .duplicate-hint {
    color: #64748b;
    font-size: 0.82rem;
    line-height: 1.5;
  }

  .history-regenerate-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .regenerate-button {
    justify-self: start;
    min-height: 42px;
    margin: 0;
    font-size: 0.88rem;
  }

  .duplicate-hint {
    margin: 0;
    color: #92400e;
  }

  @media (max-width: 640px) {
    .history-regenerate {
      padding: 14px;
    }

    .history-regenerate-grid {
      grid-template-columns: 1fr;
    }

    .regenerate-button {
      width: 100%;
    }
  }
</style>
