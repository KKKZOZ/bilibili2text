<script setup>
  import ToggleSwitch from '../common/ToggleSwitch.vue'
  import SummaryPresetPicker from '../common/SummaryPresetPicker.vue'
  import SummaryProfileSelect from '../common/SummaryProfileSelect.vue'

  defineProps({
    enabled: Boolean,
    autoGenerateFancyHtml: Boolean,
    isOpenPublic: Boolean,
    selectedProfile: { type: String, default: '' },
    selectedPreset: { type: String, default: '' },
    profiles: { type: Array, default: () => [] },
    presets: { type: Array, default: () => [] },
    profilesLoading: Boolean,
    presetsLoading: Boolean,
    profileError: { type: String, default: '' },
    presetError: { type: String, default: '' },
    customPromptTemplate: { type: String, default: '' },
    fallbackPromptTemplate: { type: String, default: '' },
    customPresetValue: { type: String, required: true }
  })

  const emit = defineEmits([
    'update:enabled',
    'update:autoGenerateFancyHtml',
    'update:selectedProfile',
    'update:selectedPreset',
    'retryProfiles',
    'retryPresets'
  ])
</script>

<template>
  <ToggleSwitch
    id="enable-summary"
    :model-value="enabled"
    label="启用 LLM 整理总结"
    @update:model-value="emit('update:enabled', $event)"
  />
  <div v-if="enabled" class="process-summary-config">
    <div class="process-summary-head">
      <h3>总结参数</h3>
      <p>
        选择模型配置与总结模板，生成更符合用途的总结内容。
        <template v-if="isOpenPublic">
          选择“用户自定义”时，会使用你在 API Key 页面保存的模板。
        </template>
      </p>
    </div>
    <ToggleSwitch
      id="auto-generate-fancy-html"
      :model-value="autoGenerateFancyHtml"
      label="总结完成后自动生成 Fancy HTML"
      compact
      @update:model-value="emit('update:autoGenerateFancyHtml', $event)"
    />
    <p class="preset-hint">
      总结文件会先显示，Fancy HTML 稍后在后台生成并自动加入列表。
    </p>
    <SummaryProfileSelect
      id="summary-profile-select"
      :model-value="selectedProfile"
      :profiles="profiles"
      :loading="profilesLoading"
      :error="profileError"
      @update:model-value="emit('update:selectedProfile', $event)"
      @retry="emit('retryProfiles')"
    />
    <SummaryPresetPicker
      id="summary-preset-select"
      :model-value="selectedPreset"
      :presets="presets"
      :loading="presetsLoading"
      :error="presetError"
      :custom-prompt-template="customPromptTemplate"
      :fallback-prompt-template="fallbackPromptTemplate"
      :custom-preset-value="customPresetValue"
      preview
      @update:model-value="emit('update:selectedPreset', $event)"
      @retry="emit('retryPresets')"
    />
  </div>
</template>

<style scoped>
  .process-summary-config {
    display: grid;
    gap: 16px;
    padding: 24px;
    border: 1px solid rgba(255, 255, 255, 0.6);
    border-radius: 20px;
    background: linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.7),
      rgba(248, 253, 255, 0.5)
    );
    box-shadow: 0 8px 24px -8px rgba(15, 23, 42, 0.05);
  }

  .process-summary-head {
    display: grid;
    gap: 6px;
  }

  .process-summary-head h3,
  .process-summary-head p {
    margin: 0;
  }

  .process-summary-head h3 {
    font-size: 1.15rem;
  }

  .process-summary-head p {
    color: #475569;
    font-size: 0.88rem;
    line-height: 1.55;
  }

  @media (max-width: 640px) {
    .process-summary-config {
      padding: 18px;
    }
  }
</style>
