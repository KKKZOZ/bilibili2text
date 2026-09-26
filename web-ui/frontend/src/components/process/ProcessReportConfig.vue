<script setup>
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
    <ToggleSwitch
      id="enable-reading-report"
      :model-value="enabled"
      label="生成阅读报告"
      @update:model-value="emit('update:enabled', $event)"
    />
    <p>
      从完整转写生成可阅读、分享的 HTML 报告，支持导出长图。可独立于 Markdown
      总结开启。
    </p>
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
      <p>
        使用所选模型对应的 API Key；自定义服务沿用 API Key
        页面保存的地址和模型。模型需支持工具调用，报告会产生独立的模型费用。
      </p>
    </div>
  </section>
</template>

<style scoped>
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
