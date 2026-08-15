<script setup>
  import { AlertCircle, CheckCircle2 } from 'lucide-vue-next'
  import InlineNotice from '../common/InlineNotice.vue'

  defineProps({
    configured: Boolean,
    modelValue: { type: String, default: '' },
    error: { type: String, default: '' },
    success: { type: String, default: '' }
  })
  const emit = defineEmits(['update:modelValue', 'save', 'reset', 'clear'])
</script>

<template>
  <div class="provider-section">
    <h3>自定义总结模板 <span>可选</span></h3>
    <p>
      保存后可在新建转录或历史重生成中选择“用户自定义”，模板必须包含
      <code>{content}</code> 占位符。
    </p>
    <div class="status-row">
      <span>当前状态</span>
      <strong :class="configured ? 'ok' : 'missing'">
        <CheckCircle2 v-if="configured" :size="14" /><AlertCircle
          v-else
          :size="14"
        />
        {{ configured ? '已保存' : '未保存' }}
      </strong>
    </div>
    <label for="summary-template">模板正文</label>
    <textarea
      id="summary-template"
      :value="modelValue"
      rows="16"
      spellcheck="false"
      placeholder="请输入总结模板，必须包含 {content} 占位符"
      @input="emit('update:modelValue', $event.target.value)"
    ></textarea>
    <div class="actions">
      <button class="submit" type="button" @click="emit('save')">
        {{ configured ? '更新模板' : '保存模板' }}
      </button>
      <button type="button" @click="emit('reset')">恢复系统默认模板</button>
      <button type="button" :disabled="!configured" @click="emit('clear')">
        清除
      </button>
    </div>
    <InlineNotice v-if="error">{{ error }}</InlineNotice>
    <InlineNotice v-if="success" kind="success">{{ success }}</InlineNotice>
  </div>
</template>

<style scoped>
  .provider-section {
    display: grid;
    gap: 10px;
    padding: 22px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
    box-shadow: var(--panel-shadow);
  }
  h3,
  p {
    margin: 0;
  }
  h3 {
    font-size: 1rem;
  }
  h3 span {
    margin-left: 5px;
    padding: 2px 6px;
    border-radius: 4px;
    background: #f1f5f9;
    color: #64748b;
    font-size: 0.68rem;
  }
  p {
    color: var(--text-muted);
    font-size: 0.84rem;
    line-height: 1.6;
  }
  .status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.82rem;
  }
  .status-row strong {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 8px;
    border-radius: 5px;
  }
  .ok {
    background: #ecfdf5;
    color: #047857;
  }
  .missing {
    background: #fff7ed;
    color: #c2410c;
  }
  label {
    color: var(--text-soft);
    font-size: 0.82rem;
    font-weight: 700;
  }
  textarea {
    width: 100%;
    resize: vertical;
    padding: 12px;
    border: 1px solid var(--line);
    border-radius: 8px;
    outline: 0;
    font: inherit;
    font-family: ui-monospace, monospace;
    line-height: 1.55;
  }
  textarea:focus {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.1);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .actions button {
    min-height: 36px;
    padding: 0 13px;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
    font-weight: 700;
    cursor: pointer;
  }
  .actions .submit {
    min-height: 36px;
    margin: 0;
    background: var(--brand);
    color: #fff;
  }
</style>
