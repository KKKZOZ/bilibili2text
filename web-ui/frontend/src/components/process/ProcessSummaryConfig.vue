<script setup>
  import ToggleSwitch from '../common/ToggleSwitch.vue'
  import HelpTooltip from '../common/HelpTooltip.vue'
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
          选择“用户自定义”时，会使用在 API Key 页面保存的模板。
        </template>
      </p>
    </div>
    <div class="option-toggle-row">
      <ToggleSwitch
        id="auto-generate-fancy-html"
        :model-value="autoGenerateFancyHtml"
        label="生成 Fancy HTML"
        compact
        @update:model-value="emit('update:autoGenerateFancyHtml', $event)"
      />
      <HelpTooltip id="fancy-html-help-tooltip" label="查看 Fancy HTML 说明">
        Fancy HTML
        是由总结内容生成的独立网页版本，提供更适合阅读和分享的排版。开启后会在后台生成，不影响
        Markdown 总结先行显示。
      </HelpTooltip>
    </div>
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
    gap: 14px;
    padding: 18px 0 0;
    border-top: 1px solid var(--line);
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
    font-size: 1rem;
  }

  .process-summary-head p {
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.55;
  }

  .option-toggle-row {
    display: flex;
    align-items: center;
    gap: 3px;
  }
</style>
