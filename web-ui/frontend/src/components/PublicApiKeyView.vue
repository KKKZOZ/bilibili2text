<script setup>
import { onMounted, ref } from 'vue';
import { AlertCircle, CheckCircle2, KeyRound, LoaderCircle, Shield } from 'lucide-vue-next';

const emit = defineEmits(['apiKeyUpdated']);

const apiKeyInput = ref('');
const configured = ref(false);
const maskedKey = ref('');
const loading = ref(false);
const saving = ref(false);
const clearing = ref(false);
const error = ref('');
const success = ref('');

const parseJsonSafely = async (resp, fallbackMessage) => {
  const raw = await resp.text();
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`${fallbackMessage}（服务返回了非 JSON 响应，HTTP ${resp.status}）`);
  }
};

const pickApiError = (resp, data, fallbackMessage) => {
  if (
    data &&
    typeof data === 'object' &&
    typeof data.detail === 'string' &&
    data.detail.trim()
  ) {
    return data.detail;
  }
  return `${fallbackMessage}（HTTP ${resp.status}）`;
};

const applyStatus = (data) => {
  configured.value = Boolean(data?.configured);
  maskedKey.value = typeof data?.masked_key === 'string' ? data.masked_key : '';
};

const loadStatus = async () => {
  loading.value = true;
  error.value = '';
  try {
    const resp = await fetch('/api/open-public/api-key');
    const data = await parseJsonSafely(resp, '获取 API Key 状态失败');
    if (!resp.ok) {
      throw new Error(pickApiError(resp, data, '获取 API Key 状态失败'));
    }
    applyStatus(data);
  } catch (err) {
    error.value = err instanceof Error ? err.message : '获取 API Key 状态失败';
  } finally {
    loading.value = false;
  }
};

const saveApiKey = async () => {
  const apiKey = apiKeyInput.value.trim();
  if (!apiKey) {
    error.value = '请输入 API Key';
    success.value = '';
    return;
  }

  saving.value = true;
  error.value = '';
  success.value = '';
  try {
    const resp = await fetch('/api/open-public/api-key', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ api_key: apiKey }),
    });
    const data = await parseJsonSafely(resp, '保存 API Key 失败');
    if (!resp.ok) {
      throw new Error(pickApiError(resp, data, '保存 API Key 失败'));
    }
    applyStatus(data);
    apiKeyInput.value = '';
    success.value = 'API Key 已更新。后续转录和总结将使用该 Key。';
    emit('apiKeyUpdated');
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存 API Key 失败';
  } finally {
    saving.value = false;
  }
};

const clearApiKey = async () => {
  clearing.value = true;
  error.value = '';
  success.value = '';
  try {
    const resp = await fetch('/api/open-public/api-key', {
      method: 'DELETE',
    });
    const data = await parseJsonSafely(resp, '清除 API Key 失败');
    if (!resp.ok) {
      throw new Error(pickApiError(resp, data, '清除 API Key 失败'));
    }
    applyStatus(data);
    apiKeyInput.value = '';
    success.value = 'API Key 已清除。未重新设置前无法提交任务。';
    emit('apiKeyUpdated');
  } catch (err) {
    error.value = err instanceof Error ? err.message : '清除 API Key 失败';
  } finally {
    clearing.value = false;
  }
};

onMounted(() => {
  void loadStatus();
});
</script>

<template>
  <section class="settings-layout">
    <article class="panel panel-settings">
      <header class="settings-header">
        <div class="settings-badge">
          <Shield :size="14" />
          <span>open-public</span>
        </div>
        <h2>阿里云 API Key</h2>
        <p>当前模式仅支持阿里云 DashScope。转录和总结都会使用这里设置的同一个 Key。</p>
      </header>

      <div v-if="loading" class="settings-loading">
        <LoaderCircle :size="16" class="spin" />
        <span>正在加载配置...</span>
      </div>

      <template v-else>
        <div class="status-row">
          <span class="status-label">当前状态</span>
          <span :class="['status-pill', configured ? 'ok' : 'missing']">
            <CheckCircle2 v-if="configured" :size="14" />
            <AlertCircle v-else :size="14" />
            <span>{{ configured ? '已配置' : '未配置' }}</span>
          </span>
        </div>

        <p v-if="configured && maskedKey" class="status-note">
          已保存 Key：<code>{{ maskedKey }}</code>
        </p>

        <label for="open-public-api-key" class="field-label">DashScope API Key</label>
        <div class="field-row">
          <KeyRound :size="16" />
          <input
            id="open-public-api-key"
            v-model="apiKeyInput"
            type="password"
            placeholder="请输入 sk-... 格式的 API Key"
            autocomplete="off"
          />
        </div>

        <div class="actions">
          <button class="submit" type="button" :disabled="saving" @click="saveApiKey">
            <LoaderCircle v-if="saving" :size="16" class="spin" />
            <span>{{ saving ? '保存中...' : '保存 API Key' }}</span>
          </button>
          <button
            class="clear-button"
            type="button"
            :disabled="clearing || !configured"
            @click="clearApiKey"
          >
            <LoaderCircle v-if="clearing" :size="16" class="spin" />
            <span>{{ clearing ? '清除中...' : '清除已保存 Key' }}</span>
          </button>
        </div>
      </template>

      <p v-if="error" class="inline-error">
        <AlertCircle :size="16" />
        <span>{{ error }}</span>
      </p>
      <p v-if="success" class="success-note">
        <CheckCircle2 :size="16" />
        <span>{{ success }}</span>
      </p>
    </article>
  </section>
</template>

<style scoped>
.settings-layout {
  position: relative;
  z-index: 2;
  max-width: 1160px;
  margin: 0 auto;
}

.panel-settings {
  padding: 28px;
  display: grid;
  gap: 14px;
}

.settings-header h2 {
  margin: 12px 0 8px;
  font-size: 1.28rem;
}

.settings-header p {
  margin: 0;
  color: var(--text-soft);
  line-height: 1.6;
  max-width: 68ch;
}

.settings-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 11px;
  border-radius: 999px;
  border: 1px solid #99f6e4;
  background: #ecfeff;
  color: #0f766e;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.settings-loading {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  min-height: 44px;
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.status-label {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text-soft);
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 700;
}

.status-pill.ok {
  background: #ecfdf5;
  color: #15803d;
  border: 1px solid #86efac;
}

.status-pill.missing {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fca5a5;
}

.status-note {
  margin: 0;
  font-size: 0.84rem;
  color: var(--text-muted);
}

.status-note code {
  font-family: "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
}

.field-label {
  font-size: 0.86rem;
  color: var(--text-soft);
  font-weight: 600;
}

.field-row {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.9);
  border-radius: 14px;
  padding: 0 13px;
  min-height: 48px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.field-row:focus-within {
  border-color: #22d3ee;
  box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.16);
}

.field-row svg {
  color: #64748b;
  flex-shrink: 0;
}

.field-row input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-main);
  height: 46px;
  font-size: 0.95rem;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.clear-button {
  margin-top: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 13px;
  font-size: 0.9rem;
  font-weight: 700;
  cursor: pointer;
  min-height: 46px;
  padding: 0 16px;
  border: 1px solid #fecaca;
  color: #b91c1c;
  background: #fff1f2;
  transition: transform 0.16s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}

.clear-button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 10px 20px rgba(185, 28, 28, 0.12);
}

.clear-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.success-note {
  margin: 0;
  color: var(--success);
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 0.9rem;
}

@media (max-width: 640px) {
  .panel-settings {
    padding: 22px;
  }

  .actions {
    width: 100%;
  }

  .submit,
  .clear-button {
    width: 100%;
  }
}
</style>
