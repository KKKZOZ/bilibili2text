<script setup>
  import { AlertCircle, CheckCircle2, KeyRound } from 'lucide-vue-next'
  import InlineNotice from '../common/InlineNotice.vue'

  defineProps({
    title: { type: String, required: true },
    required: Boolean,
    configured: Boolean,
    maskedKey: { type: String, default: '' },
    modelValue: { type: String, default: '' },
    testing: Boolean,
    error: { type: String, default: '' },
    success: { type: String, default: '' },
    fieldId: { type: String, required: true },
    placeholder: { type: String, default: '请输入 API Key' }
  })

  const emit = defineEmits(['update:modelValue', 'save', 'test', 'clear'])
</script>

<template>
  <div class="provider-section">
    <h3>
      {{ title }}
      <span :class="required ? 'required' : 'optional'">{{
        required ? '必填' : '可选'
      }}</span>
    </h3>
    <div class="description"><slot /></div>
    <div class="status-row">
      <span>当前状态</span>
      <strong :class="configured ? 'ok' : 'missing'">
        <CheckCircle2 v-if="configured" :size="14" />
        <AlertCircle v-else :size="14" />
        {{ configured ? '已配置' : '未配置' }}
      </strong>
    </div>
    <p v-if="configured && maskedKey" class="status-note">
      已保存 Key：<code>{{ maskedKey }}</code>
    </p>
    <slot name="status-note"></slot>
    <label :for="fieldId">{{ title }} API Key</label>
    <div class="field-row">
      <KeyRound :size="16" />
      <input
        :id="fieldId"
        :value="modelValue"
        type="password"
        :placeholder="placeholder"
        autocomplete="off"
        @input="emit('update:modelValue', $event.target.value)"
      />
    </div>
    <div class="actions">
      <button class="submit" type="button" @click="emit('save')">
        {{ configured ? '更新' : '保存' }}
      </button>
      <button type="button" :disabled="testing" @click="emit('test')">
        {{ testing ? '测试中' : '测试连接' }}
      </button>
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
    padding: 22px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.62);
  }

  h3 {
    margin: 0 0 8px;
    font-size: 1rem;
  }
  h3 span {
    margin-left: 5px;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.68rem;
  }
  h3 .required {
    background: #fef2f2;
    color: #b91c1c;
  }
  h3 .optional {
    background: #f1f5f9;
    color: #64748b;
  }
  .description {
    color: var(--text-muted);
    font-size: 0.84rem;
    line-height: 1.6;
  }
  .description :deep(p) {
    margin: 0 0 14px;
  }
  .description :deep(a) {
    color: var(--brand-strong);
  }

  .status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 12px 0;
    font-size: 0.82rem;
  }
  .status-row strong {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 8px;
    border-radius: 5px;
  }
  .status-row .ok {
    background: #ecfdf5;
    color: #047857;
  }
  .status-row .missing {
    background: #fff7ed;
    color: #c2410c;
  }
  .status-note {
    margin: 0 0 12px;
    color: var(--text-muted);
    font-size: 0.8rem;
  }
  label {
    display: block;
    margin-bottom: 6px;
    color: var(--text-soft);
    font-size: 0.82rem;
    font-weight: 700;
  }
  .field-row {
    display: flex;
    align-items: center;
    gap: 9px;
    min-height: 42px;
    padding: 0 12px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
  }
  .field-row svg {
    flex: 0 0 auto;
    color: #64748b;
  }
  input {
    width: 100%;
    height: 40px;
    border: 0;
    outline: 0;
    background: transparent;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
  }
  .actions button {
    min-height: 36px;
    padding: 0 13px;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
    color: var(--text-soft);
    font-weight: 700;
    cursor: pointer;
  }
  .actions .submit {
    min-height: 36px;
    margin: 0;
    background: var(--brand);
    color: #fff;
  }
  .actions button:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }
</style>
