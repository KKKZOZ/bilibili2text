<script setup>
  import GenerationExamplePreview from './GenerationExamplePreview.vue'
  import ReportModeSelect from './ReportModeSelect.vue'
  import ToggleSwitch from '../common/ToggleSwitch.vue'
  import SummaryProfileSelect from '../common/SummaryProfileSelect.vue'

  const props = defineProps({
    enabled: Boolean,
    options: { type: Object, required: true },
    profiles: { type: Array, default: () => [] },
    defaultProfile: { type: String, default: '' },
    loading: Boolean,
    error: { type: String, default: '' }
  })
  const emit = defineEmits(['update:enabled', 'update:options', 'retry'])
  const update = (key, value) =>
    emit('update:options', { ...props.options, [key]: value })
</script>

<template>
  <section class="report-config">
    <div class="generation-toggle-row">
      <ToggleSwitch
        id="enable-reading-report"
        :model-value="enabled"
        label="生成阅读报告"
        @update:model-value="emit('update:enabled', $event)"
      />
      <GenerationExamplePreview kind="report" />
    </div>

    <div v-if="enabled" class="report-fields">
      <ReportModeSelect
        :model-value="options.mode"
        @update:model-value="update('mode', $event)"
      />
      <SummaryProfileSelect
        id="report-profile"
        label="报告模型"
        :model-value="options.profile || defaultProfile"
        :profiles="profiles"
        :loading="loading"
        :error="error"
        @update:model-value="update('profile', $event)"
        @retry="emit('retry')"
      />
    </div>
  </section>
</template>

<style scoped>
  .generation-toggle-row {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 16px;
  }
  .generation-description {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.6;
  }

  .report-config {
    display: grid;
    gap: 12px;
    border-top: 1px solid var(--line);
    padding-top: 18px;
  }
  .report-config p {
    margin: 0;
    color: var(--text-muted);
    font-size: 0.82rem;
    line-height: 1.6;
  }
  .report-fields {
    display: grid;
    gap: 10px;
  }
</style>
