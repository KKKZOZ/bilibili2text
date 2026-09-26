<script setup>
  import { ref } from 'vue'
  import { LoaderCircle } from 'lucide-vue-next'
  import SummaryProfileSelect from '../common/SummaryProfileSelect.vue'
  import InlineNotice from '../common/InlineNotice.vue'
  import ReportModeSelect from '../process/ReportModeSelect.vue'

  const props = defineProps({
    profiles: { type: Array, default: () => [] },
    defaultProfile: { type: String, default: '' },
    loading: Boolean,
    status: { type: String, default: 'idle' },
    error: { type: String, default: '' },
    hasTranscript: Boolean
  })
  const emit = defineEmits(['generate'])
  const mode = ref('standard')
  const profile = ref('')
  const submit = () =>
    emit('generate', {
      mode: mode.value,
      profile: profile.value || props.defaultProfile
    })
</script>

<template>
  <section class="history-report-config">
    <div class="history-report-head">
      <p>重新生成配置</p>
      <h3>阅读报告参数</h3>
      <p>
        直接使用完整转录生成阅读报告，无需先生成总结。生成完成后自动加入文件列表。
      </p>
    </div>
    <fieldset :disabled="loading" class="report-options">
      <ReportModeSelect v-model="mode" />
      <SummaryProfileSelect
        id="history-report-profile"
        label="报告模型"
        :model-value="profile || defaultProfile"
        :profiles="profiles"
        :disabled="loading"
        @update:model-value="profile = $event"
      />
    </fieldset>
    <button
      class="submit"
      type="button"
      :disabled="loading || !hasTranscript || !profiles.length"
      @click="submit"
    >
      <LoaderCircle v-if="loading" :size="16" class="spin" />
      {{ loading ? '阅读报告生成中...' : '生成阅读报告' }}
    </button>
    <div class="generation-feedback">
      <InlineNotice v-if="!hasTranscript"
        >缺少完整转录文件，无法生成阅读报告。</InlineNotice
      >
      <InlineNotice v-if="error">{{ error }}</InlineNotice>
      <InlineNotice v-else-if="status === 'succeeded'" kind="success"
        >阅读报告已生成，可在文件列表中查看。</InlineNotice
      >
    </div>
  </section>
</template>

<style scoped>
  .generation-feedback {
    display: grid;
    gap: 10px;
  }
  .history-report-config {
    display: grid;
    gap: 16px;
    margin: 20px 0;
    padding: 18px 0;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }
  .history-report-head {
    display: grid;
    gap: 5px;
  }
  .history-report-head > p:first-child {
    color: #0284c7;
    font-size: 0.72rem;
    font-weight: 800;
  }
  h3 {
    font-size: 1rem;
  }
  h3,
  p {
    margin: 0;
  }
  p {
    color: var(--text-muted);
    font-size: 0.86rem;
    line-height: 1.6;
  }
  .report-options {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
    padding: 0;
    margin: 0;
    border: 0;
    min-width: 0;
  }
  button.submit {
    justify-self: start;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  @media (max-width: 640px) {
    .report-options {
      grid-template-columns: 1fr;
    }
  }
</style>
