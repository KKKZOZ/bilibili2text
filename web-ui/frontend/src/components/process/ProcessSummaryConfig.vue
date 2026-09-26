<script setup>
  import { Infinity as InfinityIcon, Minus, Plus } from 'lucide-vue-next'
  import ToggleSwitch from '../common/ToggleSwitch.vue'
  import HelpTooltip from '../common/HelpTooltip.vue'
  import SummaryPresetPicker from '../common/SummaryPresetPicker.vue'
  import SummaryProfileSelect from '../common/SummaryProfileSelect.vue'

  const props = defineProps({
    allowComments: Boolean,
    disabled: Boolean,
    includeComments: Boolean,
    downloadAllComments: Boolean,
    commentLimit: { type: Number, default: 200 },
    enabled: Boolean,
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
    'update:includeComments',
    'update:downloadAllComments',
    'update:commentLimit',
    'update:selectedProfile',
    'update:selectedPreset',
    'retryProfiles',
    'retryPresets'
  ])
  const setCommentLimit = (value) => {
    const parsed = Number(value)
    emit(
      'update:commentLimit',
      Number.isFinite(parsed)
        ? Math.min(1000, Math.max(1, Math.floor(parsed)))
        : 200
    )
  }
  const adjustCommentLimit = (delta) =>
    setCommentLimit(props.commentLimit + delta)
</script>

<template>
  <ToggleSwitch
    id="enable-summary"
    :model-value="enabled"
    label="生成总结"
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
    >
      <template #label-addon>
        <HelpTooltip
          id="summary-preset-help-tooltip"
          label="查看总结模板选择建议"
        >
          <span class="template-guidance">
            <span
              ><strong>金融主题：</strong>单人投资复盘、直播或个股分析。</span
            >
            <span
              ><strong>投资播客：</strong
              >需要区分发言者和观点的多人投资对话。</span
            >
            <span
              ><strong>学习笔记：</strong>课程、讲座或教程，适合复习整理。</span
            >
            <span><strong>通用总结：</strong>访谈、资讯及其他一般内容。</span>
            <span v-if="isOpenPublic">
              <strong>用户自定义：</strong>已有明确结构或特殊整理要求。
            </span>
          </span>
        </HelpTooltip>
      </template>
    </SummaryPresetPicker>
    <div v-if="allowComments" class="comments-field">
      <div class="option-toggle-row">
        <ToggleSwitch
          id="include-comments"
          :model-value="includeComments"
          label="总结精选评论"
          @update:model-value="emit('update:includeComments', $event)"
        />
        <HelpTooltip id="comments-help-tooltip" label="查看精选评论下载说明">
          仅用于 LLM 整理总结，不影响阅读报告。支持 B
          站和小宇宙。默认按热门排序下载前 200
          条主评论，每条主评论的全部子评论都会下载。
        </HelpTooltip>
      </div>
      <div v-if="includeComments" class="comments-options">
        <span class="comments-options-label">主评论数量</span>
        <div class="comment-range-control">
          <div
            class="comment-range-segments"
            role="group"
            aria-label="主评论下载范围"
          >
            <button
              type="button"
              class="comment-range-segment"
              :class="{ active: !downloadAllComments }"
              :disabled="disabled"
              @click="emit('update:downloadAllComments', false)"
            >
              指定数量
            </button>
            <button
              type="button"
              class="comment-range-segment"
              :class="{ active: downloadAllComments }"
              :disabled="disabled"
              @click="emit('update:downloadAllComments', true)"
            >
              全部
            </button>
          </div>
          <div v-if="!downloadAllComments" class="comment-limit-stepper">
            <button
              type="button"
              :disabled="disabled"
              aria-label="减少主评论数量"
              @click="adjustCommentLimit(-10)"
            >
              <Minus :size="15" />
            </button>
            <input
              :value="commentLimit"
              type="number"
              min="1"
              max="1000"
              :disabled="disabled"
              aria-label="主评论数量"
              @change="setCommentLimit($event.target.value)"
            />
            <span>条</span>
            <button
              type="button"
              :disabled="disabled"
              aria-label="增加主评论数量"
              @click="adjustCommentLimit(10)"
            >
              <Plus :size="15" />
            </button>
          </div>
          <div v-else class="comment-all-state">
            <InfinityIcon :size="16" />
            <span>不限数量</span>
          </div>
        </div>
      </div>
    </div>
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

  .template-guidance {
    display: grid;
    gap: 5px;
  }

  .template-guidance strong {
    color: var(--text-main);
  }
  .comments-field {
    display: grid;
    gap: 10px;
  }

  .comments-options {
    display: grid;
    grid-template-columns: 92px minmax(0, 330px);
    align-items: center;
    gap: 9px 12px;
  }

  .comments-options-label {
    color: var(--text-soft);
    font-size: 0.86rem;
    font-weight: 700;
  }

  .comment-range-control {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 142px;
    align-items: stretch;
    height: 42px;
    overflow: hidden;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
  }

  .comment-range-segments {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 2px;
    padding: 3px;
    border-right: 1px solid var(--line);
    background: #f1f4f7;
  }

  .comment-range-segment {
    min-width: 0;
    padding: 0 8px;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: #64748b;
    font-size: 0.8rem;
    font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
  }

  .comment-range-segment.active {
    background: #fff;
    color: var(--brand-strong);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
  }

  .comment-range-segment:focus-visible,
  .comment-limit-stepper button:focus-visible,
  .comment-limit-stepper input:focus-visible {
    position: relative;
    z-index: 1;
    outline: 2px solid rgba(15, 143, 131, 0.35);
    outline-offset: -2px;
  }

  .comment-range-segment:disabled,
  .comment-limit-stepper button:disabled,
  .comment-limit-stepper input:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .comment-limit-stepper {
    display: flex;
    align-items: center;
    min-width: 0;
  }

  .comment-limit-stepper button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    color: #64748b;
    cursor: pointer;
  }

  .comment-limit-stepper input {
    min-width: 0;
    width: 58px;
    height: 100%;
    border: 0;
    outline: 0;
    appearance: textfield;
    font: inherit;
    font-variant-numeric: tabular-nums;
    text-align: center;
  }

  .comment-limit-stepper input::-webkit-inner-spin-button,
  .comment-limit-stepper input::-webkit-outer-spin-button {
    margin: 0;
    appearance: none;
  }

  .comment-limit-stepper span {
    padding-right: 3px;
    color: #64748b;
    font-size: 0.78rem;
  }

  .comment-limit-stepper button:hover:not(:disabled) {
    background: var(--brand-soft);
    color: var(--brand-strong);
  }

  .comment-all-state {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    color: #64748b;
    font-size: 0.78rem;
    font-weight: 700;
  }

  .comment-all-state svg {
    color: var(--brand);
  }

  @media (max-width: 640px) {
    .comments-options {
      grid-template-columns: 1fr;
    }

    .comment-range-control {
      grid-template-columns: minmax(0, 1fr) 136px;
    }
  }
</style>
