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
          选择“用户自定义”时，会使用在 API Key 页面保存的模板。
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
    <InlineNotice v-if="error">{{ error }}</InlineNotice>
    <InlineNotice v-if="success" kind="success">{{ success }}</InlineNotice>
  </div>
</template>

<style scoped>
  .history-regenerate {
    display: grid;
    gap: 16px;
    margin: 20px 0;
    padding: 18px 0;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
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

  .history-regenerate-head > p:last-child {
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

  @media (max-width: 640px) {
    .history-regenerate-grid {
      grid-template-columns: 1fr;
    }

    .regenerate-button {
      width: 100%;
    }
  }
</style>
