<script setup>
  import { AlertCircle, CheckCircle2, KeyRound } from 'lucide-vue-next'
  import InlineNotice from '../common/InlineNotice.vue'

  defineProps({
    configured: Boolean,
    maskedKey: { type: String, default: '' },
    savedBaseUrl: { type: String, default: '' },
    savedModel: { type: String, default: '' },
    baseUrl: { type: String, default: '' },
    model: { type: String, default: '' },
    apiKey: { type: String, default: '' },
    testing: Boolean,
    error: { type: String, default: '' },
    success: { type: String, default: '' }
  })
  const emit = defineEmits([
    'update:baseUrl',
    'update:model',
    'update:apiKey',
    'save',
    'test',
    'clear'
  ])
</script>

<template>
  <div class="provider-section">
    <h3>自定义 OpenAI-compatible LLM <span>可选</span></h3>
    <p>配置后可用于总结、知识库问答和 Fancy HTML。</p>
    <div class="status-row">
      <span>当前状态</span>
      <strong :class="configured ? 'ok' : 'missing'">
        <CheckCircle2 v-if="configured" :size="14" /><AlertCircle
          v-else
          :size="14"
        />
        {{ configured ? '已配置' : '未配置' }}
      </strong>
    </div>
    <p v-if="configured" class="saved">
      {{ savedBaseUrl }} · {{ savedModel }} · <code>{{ maskedKey }}</code>
    </p>
    <label for="custom-llm-base-url">base_url</label>
    <input
      id="custom-llm-base-url"
      :value="baseUrl"
      placeholder="https://api.example.com/v1"
      @input="emit('update:baseUrl', $event.target.value)"
    />
    <label for="custom-llm-model">model</label>
    <input
      id="custom-llm-model"
      :value="model"
      placeholder="请输入模型名称"
      @input="emit('update:model', $event.target.value)"
    />
    <label for="custom-llm-api-key">API Key</label>
    <div class="key-input">
      <KeyRound :size="16" /><input
        id="custom-llm-api-key"
        :value="apiKey"
        type="password"
        placeholder="请输入 API Key"
        @input="emit('update:apiKey', $event.target.value)"
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
    display: grid;
    gap: 9px;
    padding: 22px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.62);
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
  input {
    width: 100%;
    min-height: 42px;
    padding: 0 12px;
    border: 1px solid var(--line);
    border-radius: 8px;
    outline: 0;
  }
  .key-input {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-left: 12px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #fff;
  }
  .key-input input {
    border: 0;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 3px;
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
