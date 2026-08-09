<script setup>
  import { onMounted, ref } from 'vue'
  import {
    AlertCircle,
    CheckCircle2,
    KeyRound,
    Shield,
    Info
  } from 'lucide-vue-next'

  const emit = defineEmits(['apiKeyUpdated'])

  const LOCAL_API_KEY_KEY = 'b2t.public-api-key'
  const LOCAL_DEEPSEEK_API_KEY_KEY = 'b2t.public-deepseek-api-key'
  const LOCAL_CUSTOM_LLM_BASE_URL_KEY = 'b2t.public-custom-llm-base-url'
  const LOCAL_CUSTOM_LLM_API_KEY_KEY = 'b2t.public-custom-llm-api-key'
  const LOCAL_CUSTOM_LLM_MODEL_KEY = 'b2t.public-custom-llm-model'
  const LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY =
    'b2t.open-public-summary-template'

  const props = defineProps({
    summaryDefaultPromptTemplate: {
      type: String,
      default: ''
    }
  })

  // Aliyun key state
  const aliyunKeyInput = ref('')
  const aliyunConfigured = ref(false)
  const aliyunMaskedKey = ref('')
  const aliyunError = ref('')
  const aliyunSuccess = ref('')
  const isTestingAliyun = ref(false)

  // DeepSeek key state
  const deepseekKeyInput = ref('')
  const deepseekConfigured = ref(false)
  const deepseekMaskedKey = ref('')
  const deepseekError = ref('')
  const deepseekSuccess = ref('')
  const isTestingDeepseek = ref(false)

  // Custom OpenAI-compatible LLM state
  const customLlmBaseUrlInput = ref('')
  const customLlmApiKeyInput = ref('')
  const customLlmModelInput = ref('')
  const customLlmConfigured = ref(false)
  const customLlmMaskedKey = ref('')
  const customLlmSavedBaseUrl = ref('')
  const customLlmSavedModel = ref('')
  const customLlmError = ref('')
  const customLlmSuccess = ref('')
  const isTestingCustomLlm = ref(false)

  const summaryTemplateInput = ref('')
  const summaryTemplateConfigured = ref(false)
  const summaryTemplateSuccess = ref('')
  const summaryTemplateError = ref('')

  const maskKey = (key) => {
    if (!key) return ''
    if (key.length <= 8) return '*'.repeat(key.length)
    return `${key.slice(0, 4)}${'*'.repeat(12)}${key.slice(-4)}`
  }

  const loadStatus = () => {
    try {
      const aliyunKey = (
        window.localStorage.getItem(LOCAL_API_KEY_KEY) || ''
      ).trim()
      aliyunConfigured.value = aliyunKey.length > 0
      aliyunMaskedKey.value = aliyunKey ? maskKey(aliyunKey) : ''

      const dsKey = (
        window.localStorage.getItem(LOCAL_DEEPSEEK_API_KEY_KEY) || ''
      ).trim()
      deepseekConfigured.value = dsKey.length > 0
      deepseekMaskedKey.value = dsKey ? maskKey(dsKey) : ''

      const customBaseUrl = (
        window.localStorage.getItem(LOCAL_CUSTOM_LLM_BASE_URL_KEY) || ''
      ).trim()
      const customApiKey = (
        window.localStorage.getItem(LOCAL_CUSTOM_LLM_API_KEY_KEY) || ''
      ).trim()
      const customModel = (
        window.localStorage.getItem(LOCAL_CUSTOM_LLM_MODEL_KEY) || ''
      ).trim()
      customLlmConfigured.value = Boolean(
        customBaseUrl && customApiKey && customModel
      )
      customLlmMaskedKey.value = customApiKey ? maskKey(customApiKey) : ''
      customLlmSavedBaseUrl.value = customBaseUrl
      customLlmSavedModel.value = customModel
      customLlmBaseUrlInput.value = customBaseUrl
      customLlmModelInput.value = customModel

      const summaryTemplate = (
        window.localStorage.getItem(LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY) ||
        ''
      ).trim()
      summaryTemplateConfigured.value = summaryTemplate.length > 0
      summaryTemplateInput.value =
        summaryTemplate || props.summaryDefaultPromptTemplate
    } catch {
      aliyunError.value = '读取本地存储失败'
    }
  }

  const validateKey = (key, label) => {
    if (!key.startsWith('sk-')) {
      return `${label} API Key 格式不正确，应以 sk- 开头`
    }
    if (key.length < 20) {
      return `${label} API Key 长度不足，请检查是否完整`
    }
    return ''
  }

  const validateSummaryTemplate = (template) => {
    const cleaned = template.trim()
    if (!cleaned) {
      return '请输入总结模板'
    }
    if (!cleaned.includes('{content}')) {
      return '总结模板必须包含 {content} 占位符'
    }
    return ''
  }

  const normalizeBaseUrl = (baseUrl) => baseUrl.trim().replace(/\/+$/, '')

  const validateCustomLlmConfig = ({ baseUrl, apiKey, model }) => {
    const cleanedBaseUrl = normalizeBaseUrl(baseUrl)
    if (!cleanedBaseUrl) {
      return '请输入 base_url'
    }
    if (!/^https?:\/\//i.test(cleanedBaseUrl)) {
      return 'base_url 必须以 http:// 或 https:// 开头'
    }
    if (!apiKey.trim()) {
      return '请输入 API Key'
    }
    if (!model.trim()) {
      return '请输入模型名称'
    }
    return ''
  }

  const getSavedCustomLlmApiKey = () => {
    try {
      return (
        window.localStorage.getItem(LOCAL_CUSTOM_LLM_API_KEY_KEY) || ''
      ).trim()
    } catch {
      return ''
    }
  }

  const getSavedProviderApiKey = (storageKey) => {
    try {
      return (window.localStorage.getItem(storageKey) || '').trim()
    } catch {
      return ''
    }
  }

  const parseApiResponse = async (resp) => {
    const raw = await resp.text()
    if (!raw) return null
    try {
      return JSON.parse(raw)
    } catch {
      throw new Error(`响应不是有效 JSON（HTTP ${resp.status}）`)
    }
  }

  const assertSuccessfulTestResponse = (resp, data) => {
    if (!resp.ok) {
      const detail = data?.detail || data?.message || `HTTP ${resp.status}`
      throw new Error(String(detail))
    }
    const content = data?.content
    if (typeof content !== 'string' || !content.trim()) {
      throw new Error('后端测试接口返回了空响应')
    }
  }

  const testProviderConnection = async ({
    provider,
    label,
    inputValue,
    storageKey,
    setError,
    setSuccess,
    setTesting
  }) => {
    const apiKey = inputValue.trim() || getSavedProviderApiKey(storageKey)
    if (!apiKey) {
      setError('请输入 API Key，或先保存已有 Key')
      setSuccess('')
      return
    }
    const validationError = validateKey(apiKey, label)
    if (validationError) {
      setError(validationError)
      setSuccess('')
      return
    }
    setError('')
    setSuccess('')
    setTesting(true)
    try {
      const resp = await fetch('/api/open-public/api-key/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          provider,
          api_key: apiKey
        })
      })
      const data = await parseApiResponse(resp)
      assertSuccessfulTestResponse(resp, data)
      setSuccess('测试连接成功。')
    } catch (err) {
      const message = err instanceof Error ? err.message : '测试连接失败'
      setError(`测试连接失败：${message}`)
    } finally {
      setTesting(false)
    }
  }

  const saveCustomLlm = () => {
    const baseUrl = normalizeBaseUrl(customLlmBaseUrlInput.value)
    const apiKey =
      customLlmApiKeyInput.value.trim() || getSavedCustomLlmApiKey()
    const model = customLlmModelInput.value.trim()
    const validationError = validateCustomLlmConfig({ baseUrl, apiKey, model })
    if (validationError) {
      customLlmError.value = validationError
      customLlmSuccess.value = ''
      return
    }
    customLlmError.value = ''
    customLlmSuccess.value = ''
    try {
      window.localStorage.setItem(LOCAL_CUSTOM_LLM_BASE_URL_KEY, baseUrl)
      window.localStorage.setItem(LOCAL_CUSTOM_LLM_API_KEY_KEY, apiKey)
      window.localStorage.setItem(LOCAL_CUSTOM_LLM_MODEL_KEY, model)
      customLlmConfigured.value = true
      customLlmMaskedKey.value = maskKey(apiKey)
      customLlmSavedBaseUrl.value = baseUrl
      customLlmSavedModel.value = model
      customLlmApiKeyInput.value = ''
      customLlmSuccess.value =
        '自定义 LLM 已更新。后续总结、知识库问答和 Fancy HTML 将优先使用该模型。'
      emit('apiKeyUpdated')
    } catch {
      customLlmError.value = '保存失败，请检查浏览器存储权限'
    }
  }

  const clearCustomLlm = () => {
    customLlmError.value = ''
    customLlmSuccess.value = ''
    try {
      window.localStorage.removeItem(LOCAL_CUSTOM_LLM_BASE_URL_KEY)
      window.localStorage.removeItem(LOCAL_CUSTOM_LLM_API_KEY_KEY)
      window.localStorage.removeItem(LOCAL_CUSTOM_LLM_MODEL_KEY)
      customLlmConfigured.value = false
      customLlmMaskedKey.value = ''
      customLlmSavedBaseUrl.value = ''
      customLlmSavedModel.value = ''
      customLlmBaseUrlInput.value = ''
      customLlmApiKeyInput.value = ''
      customLlmModelInput.value = ''
      customLlmSuccess.value =
        '自定义 LLM 已清除。LLM 功能将回退使用 DeepSeek 或阿里云。'
      emit('apiKeyUpdated')
    } catch {
      customLlmError.value = '清除失败，请检查浏览器存储权限'
    }
  }

  const testCustomLlmConnection = async () => {
    const baseUrl = normalizeBaseUrl(customLlmBaseUrlInput.value)
    const apiKey =
      customLlmApiKeyInput.value.trim() || getSavedCustomLlmApiKey()
    const model = customLlmModelInput.value.trim()
    const validationError = validateCustomLlmConfig({ baseUrl, apiKey, model })
    if (validationError) {
      customLlmError.value = validationError
      customLlmSuccess.value = ''
      return
    }
    customLlmError.value = ''
    customLlmSuccess.value = ''
    isTestingCustomLlm.value = true
    try {
      const resp = await fetch('/api/open-public/custom-llm/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          base_url: baseUrl,
          api_key: apiKey,
          model
        })
      })
      const data = await parseApiResponse(resp)
      assertSuccessfulTestResponse(resp, data)
      customLlmSuccess.value = '测试连接成功。'
    } catch (err) {
      const message = err instanceof Error ? err.message : '测试连接失败'
      customLlmError.value = `测试连接失败：${message}`
    } finally {
      isTestingCustomLlm.value = false
    }
  }

  const testAliyunConnection = () =>
    testProviderConnection({
      provider: 'alibaba',
      label: '阿里云',
      inputValue: aliyunKeyInput.value,
      storageKey: LOCAL_API_KEY_KEY,
      setError: (message) => {
        aliyunError.value = message
      },
      setSuccess: (message) => {
        aliyunSuccess.value = message
      },
      setTesting: (value) => {
        isTestingAliyun.value = value
      }
    })

  const saveAliyunKey = () => {
    const apiKey = aliyunKeyInput.value.trim()
    if (!apiKey) {
      aliyunError.value = '请输入 API Key'
      aliyunSuccess.value = ''
      return
    }
    const validationError = validateKey(apiKey, '阿里云')
    if (validationError) {
      aliyunError.value = validationError
      aliyunSuccess.value = ''
      return
    }
    aliyunError.value = ''
    aliyunSuccess.value = ''
    try {
      window.localStorage.setItem(LOCAL_API_KEY_KEY, apiKey)
      aliyunConfigured.value = true
      aliyunMaskedKey.value = maskKey(apiKey)
      aliyunKeyInput.value = ''
      aliyunSuccess.value = '阿里云 API Key 已更新。'
      emit('apiKeyUpdated')
    } catch {
      aliyunError.value = '保存失败，请检查浏览器存储权限'
    }
  }

  const testDeepseekConnection = () =>
    testProviderConnection({
      provider: 'deepseek',
      label: 'DeepSeek',
      inputValue: deepseekKeyInput.value,
      storageKey: LOCAL_DEEPSEEK_API_KEY_KEY,
      setError: (message) => {
        deepseekError.value = message
      },
      setSuccess: (message) => {
        deepseekSuccess.value = message
      },
      setTesting: (value) => {
        isTestingDeepseek.value = value
      }
    })

  const clearAliyunKey = () => {
    aliyunError.value = ''
    aliyunSuccess.value = ''
    try {
      window.localStorage.removeItem(LOCAL_API_KEY_KEY)
      aliyunConfigured.value = false
      aliyunMaskedKey.value = ''
      aliyunSuccess.value = '阿里云 API Key 已清除。'
      emit('apiKeyUpdated')
    } catch {
      aliyunError.value = '清除失败，请检查浏览器存储权限'
    }
  }

  const saveDeepseekKey = () => {
    const apiKey = deepseekKeyInput.value.trim()
    if (!apiKey) {
      deepseekError.value = '请输入 API Key'
      deepseekSuccess.value = ''
      return
    }
    const validationError = validateKey(apiKey, 'DeepSeek')
    if (validationError) {
      deepseekError.value = validationError
      deepseekSuccess.value = ''
      return
    }
    deepseekError.value = ''
    deepseekSuccess.value = ''
    try {
      window.localStorage.setItem(LOCAL_DEEPSEEK_API_KEY_KEY, apiKey)
      deepseekConfigured.value = true
      deepseekMaskedKey.value = maskKey(apiKey)
      deepseekKeyInput.value = ''
      deepseekSuccess.value =
        'DeepSeek API Key 已更新。后续 LLM 总结、知识库问答和 Fancy HTML 将使用该 Key。'
      emit('apiKeyUpdated')
    } catch {
      deepseekError.value = '保存失败，请检查浏览器存储权限'
    }
  }

  const clearDeepseekKey = () => {
    deepseekError.value = ''
    deepseekSuccess.value = ''
    try {
      window.localStorage.removeItem(LOCAL_DEEPSEEK_API_KEY_KEY)
      deepseekConfigured.value = false
      deepseekMaskedKey.value = ''
      deepseekSuccess.value =
        'DeepSeek API Key 已清除。LLM 功能将回退使用阿里云。'
      emit('apiKeyUpdated')
    } catch {
      deepseekError.value = '清除失败，请检查浏览器存储权限'
    }
  }

  const saveSummaryTemplate = () => {
    const template = summaryTemplateInput.value
    const validationError = validateSummaryTemplate(template)
    if (validationError) {
      summaryTemplateError.value = validationError
      summaryTemplateSuccess.value = ''
      return
    }
    summaryTemplateError.value = ''
    summaryTemplateSuccess.value = ''
    try {
      window.localStorage.setItem(
        LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY,
        template.trim()
      )
      summaryTemplateConfigured.value = true
      summaryTemplateSuccess.value = '自定义总结模板已保存。'
    } catch {
      summaryTemplateError.value = '保存失败，请检查浏览器存储权限'
    }
  }

  const clearSummaryTemplate = () => {
    summaryTemplateError.value = ''
    summaryTemplateSuccess.value = ''
    try {
      window.localStorage.removeItem(LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY)
      summaryTemplateConfigured.value = false
      summaryTemplateInput.value = props.summaryDefaultPromptTemplate || ''
      summaryTemplateSuccess.value = '自定义总结模板已清除。'
    } catch {
      summaryTemplateError.value = '清除失败，请检查浏览器存储权限'
    }
  }

  const resetSummaryTemplateToDefault = () => {
    summaryTemplateError.value = ''
    summaryTemplateSuccess.value = ''
    summaryTemplateInput.value = props.summaryDefaultPromptTemplate || ''
  }

  onMounted(() => {
    loadStatus()
  })
</script>

<template>
  <section class="settings-layout">
    <article class="panel panel-settings">
      <header class="settings-header">
        <div class="settings-badge">
          <Shield :size="14" />
          <span>open-public</span>
        </div>
        <h2>API Key 配置</h2>
        <p>
          语音识别（ASR）需要<strong>阿里云 DashScope</strong> API
          Key，<strong>必须配置</strong>。如需使用 DeepSeek 模型进行 LLM
          总结、知识库问答或 Fancy HTML 生成，可<strong>额外配置</strong>
          DeepSeek API Key，然后在转录页面模型下拉框中切换到 DeepSeek 模型。
        </p>
      </header>

      <div class="privacy-notice">
        <Info :size="16" />
        <span
          ><strong>隐私提示：</strong>所有 Key
          仅持久保存在您浏览器的本地存储（localStorage）中。本网站会在测试连接或提交任务时，将对应
          Key
          临时发送到后端用于调用模型，但不会写入服务器持久存储。自定义总结模板同样只保存在本地浏览器中。</span
        >
      </div>

      <div class="provider-grid">
        <!-- Aliyun Section -->
        <div class="provider-section">
          <h3 class="provider-title">
            阿里云 DashScope <span class="required-badge">必填</span>
          </h3>
          <p class="provider-desc">
            语音识别（ASR）依赖阿里云，无此 Key 无法提交转录任务。
            <a
              class="provider-link"
              href="https://bailian.console.aliyun.com/cn-beijing/?tab=model#/api-key"
              target="_blank"
              rel="noopener noreferrer"
            >
              前往阿里云百炼创建 API Key
            </a>
          </p>

          <div class="status-row">
            <span class="status-label">当前状态</span>
            <span :class="['status-pill', aliyunConfigured ? 'ok' : 'missing']">
              <CheckCircle2 v-if="aliyunConfigured" :size="14" />
              <AlertCircle v-else :size="14" />
              <span>{{ aliyunConfigured ? '已配置' : '未配置' }}</span>
            </span>
          </div>

          <p v-if="aliyunConfigured && aliyunMaskedKey" class="status-note">
            已保存 Key：<code>{{ aliyunMaskedKey }}</code>
          </p>

          <label for="aliyun-api-key" class="field-label"
            >DashScope API Key</label
          >
          <div class="field-row">
            <KeyRound :size="16" />
            <input
              id="aliyun-api-key"
              v-model="aliyunKeyInput"
              type="password"
              placeholder="请输入 sk-... 格式的 API Key"
              autocomplete="off"
            />
          </div>

          <div class="actions">
            <button class="submit" type="button" @click="saveAliyunKey">
              <span>{{ aliyunConfigured ? '更新' : '保存' }}</span>
            </button>
            <button
              class="ghost-button"
              type="button"
              :disabled="isTestingAliyun"
              @click="testAliyunConnection"
            >
              <span>{{ isTestingAliyun ? '测试中' : '测试连接' }}</span>
            </button>
            <button
              class="clear-button"
              type="button"
              :disabled="!aliyunConfigured"
              @click="clearAliyunKey"
            >
              <span>清除</span>
            </button>
          </div>

          <p v-if="aliyunError" class="inline-error">
            <AlertCircle :size="16" />
            <span>{{ aliyunError }}</span>
          </p>
          <p v-if="aliyunSuccess" class="success-note">
            <CheckCircle2 :size="16" />
            <span>{{ aliyunSuccess }}</span>
          </p>
        </div>

        <!-- DeepSeek Section -->
        <div class="provider-section">
          <h3 class="provider-title">
            DeepSeek <span class="optional-badge">可选</span>
          </h3>
          <p class="provider-desc">
            配置后可在转录页面的模型下拉框中选择 DeepSeek 模型，用于 LLM
            总结、知识库问答和 Fancy HTML。
            <a
              class="provider-link"
              href="https://platform.deepseek.com/api_keys"
              target="_blank"
              rel="noopener noreferrer"
            >
              前往 DeepSeek 创建 API Key
            </a>
          </p>

          <div class="status-row">
            <span class="status-label">当前状态</span>
            <span
              :class="['status-pill', deepseekConfigured ? 'ok' : 'missing']"
            >
              <CheckCircle2 v-if="deepseekConfigured" :size="14" />
              <AlertCircle v-else :size="14" />
              <span>{{ deepseekConfigured ? '已配置' : '未配置' }}</span>
            </span>
          </div>

          <p v-if="deepseekConfigured && deepseekMaskedKey" class="status-note">
            已保存 Key：<code>{{ deepseekMaskedKey }}</code>
          </p>
          <p v-else class="status-note">
            未配置时将使用阿里云 Key 进行 LLM 调用。
          </p>

          <label for="deepseek-api-key" class="field-label"
            >DeepSeek API Key</label
          >
          <div class="field-row">
            <KeyRound :size="16" />
            <input
              id="deepseek-api-key"
              v-model="deepseekKeyInput"
              type="password"
              placeholder="请输入 sk-... 格式的 API Key"
              autocomplete="off"
            />
          </div>

          <div class="actions">
            <button class="submit" type="button" @click="saveDeepseekKey">
              <span>{{ deepseekConfigured ? '更新' : '保存' }}</span>
            </button>
            <button
              class="ghost-button"
              type="button"
              :disabled="isTestingDeepseek"
              @click="testDeepseekConnection"
            >
              <span>{{ isTestingDeepseek ? '测试中' : '测试连接' }}</span>
            </button>
            <button
              class="clear-button"
              type="button"
              :disabled="!deepseekConfigured"
              @click="clearDeepseekKey"
            >
              <span>清除</span>
            </button>
          </div>

          <p v-if="deepseekError" class="inline-error">
            <AlertCircle :size="16" />
            <span>{{ deepseekError }}</span>
          </p>
          <p v-if="deepseekSuccess" class="success-note">
            <CheckCircle2 :size="16" />
            <span>{{ deepseekSuccess }}</span>
          </p>
        </div>
      </div>

      <div class="provider-section">
        <h3 class="provider-title">
          自定义 OpenAI-compatible LLM
          <span class="optional-badge">可选</span>
        </h3>
        <p class="provider-desc">
          配置后将优先用于 LLM 总结、知识库问答和 Fancy HTML。端点需兼容 OpenAI
          chat/completions，base_url 示例为
          <code>https://api.example.com/v1</code>。
        </p>

        <div class="status-row">
          <span class="status-label">当前状态</span>
          <span
            :class="['status-pill', customLlmConfigured ? 'ok' : 'missing']"
          >
            <CheckCircle2 v-if="customLlmConfigured" :size="14" />
            <AlertCircle v-else :size="14" />
            <span>{{ customLlmConfigured ? '已配置' : '未配置' }}</span>
          </span>
        </div>

        <p v-if="customLlmConfigured" class="status-note">
          已保存模型：<code>{{ customLlmSavedModel }}</code>
          <span v-if="customLlmSavedBaseUrl">
            · <code>{{ customLlmSavedBaseUrl }}</code>
          </span>
          <span v-if="customLlmMaskedKey">
            · Key：<code>{{ customLlmMaskedKey }}</code>
          </span>
        </p>
        <p v-else class="status-note">
          未配置时将使用 DeepSeek；DeepSeek 也未配置时回退使用阿里云。
        </p>

        <label for="custom-llm-base-url" class="field-label">base_url</label>
        <div class="field-row">
          <input
            id="custom-llm-base-url"
            v-model="customLlmBaseUrlInput"
            type="url"
            placeholder="https://api.example.com/v1"
            autocomplete="off"
          />
        </div>

        <label for="custom-llm-model" class="field-label">model</label>
        <div class="field-row">
          <input
            id="custom-llm-model"
            v-model="customLlmModelInput"
            type="text"
            placeholder="请输入模型名称"
            autocomplete="off"
          />
        </div>

        <label for="custom-llm-api-key" class="field-label">API Key</label>
        <div class="field-row">
          <KeyRound :size="16" />
          <input
            id="custom-llm-api-key"
            v-model="customLlmApiKeyInput"
            type="password"
            placeholder="请输入 API Key"
            autocomplete="off"
          />
        </div>

        <div class="actions">
          <button class="submit" type="button" @click="saveCustomLlm">
            <span>{{ customLlmConfigured ? '更新' : '保存' }}</span>
          </button>
          <button
            class="ghost-button"
            type="button"
            :disabled="isTestingCustomLlm"
            @click="testCustomLlmConnection"
          >
            <span>{{ isTestingCustomLlm ? '测试中' : '测试连接' }}</span>
          </button>
          <button
            class="clear-button"
            type="button"
            :disabled="!customLlmConfigured"
            @click="clearCustomLlm"
          >
            <span>清除</span>
          </button>
        </div>

        <p v-if="customLlmError" class="inline-error">
          <AlertCircle :size="16" />
          <span>{{ customLlmError }}</span>
        </p>
        <p v-if="customLlmSuccess" class="success-note">
          <CheckCircle2 :size="16" />
          <span>{{ customLlmSuccess }}</span>
        </p>
      </div>

      <div class="provider-section">
        <h3 class="provider-title">
          自定义总结模板 <span class="optional-badge">可选</span>
        </h3>
        <p class="provider-desc">
          保存后，可在“新建转录”或历史重生成的总结模板下拉框中选择“用户自定义”。
          未保存时，选择该选项将无法提交。模板必须包含
          <code>{content}</code> 占位符。
        </p>

        <div class="status-row">
          <span class="status-label">当前状态</span>
          <span
            :class="[
              'status-pill',
              summaryTemplateConfigured ? 'ok' : 'missing'
            ]"
          >
            <CheckCircle2 v-if="summaryTemplateConfigured" :size="14" />
            <AlertCircle v-else :size="14" />
            <span>{{ summaryTemplateConfigured ? '已保存' : '未保存' }}</span>
          </span>
        </div>

        <label for="summary-template" class="field-label">模板正文</label>
        <textarea
          id="summary-template"
          v-model="summaryTemplateInput"
          class="template-editor"
          rows="16"
          spellcheck="false"
          placeholder="请输入总结模板，必须包含 {content} 占位符"
        ></textarea>

        <div class="actions">
          <button class="submit" type="button" @click="saveSummaryTemplate">
            <span>{{
              summaryTemplateConfigured ? '更新模板' : '保存模板'
            }}</span>
          </button>
          <button
            class="ghost-button"
            type="button"
            @click="resetSummaryTemplateToDefault"
          >
            <span>恢复系统默认模板</span>
          </button>
          <button
            class="clear-button"
            type="button"
            :disabled="!summaryTemplateConfigured"
            @click="clearSummaryTemplate"
          >
            <span>清除</span>
          </button>
        </div>

        <p v-if="summaryTemplateError" class="inline-error">
          <AlertCircle :size="16" />
          <span>{{ summaryTemplateError }}</span>
        </p>
        <p v-if="summaryTemplateSuccess" class="success-note">
          <CheckCircle2 :size="16" />
          <span>{{ summaryTemplateSuccess }}</span>
        </p>
      </div>
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

  .provider-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
    align-items: stretch;
  }

  .settings-header h2 {
    margin: 12px 0 8px;
    font-size: 1.28rem;
  }

  .settings-header p {
    margin: 0;
    color: var(--text-soft);
    line-height: 1.6;
  }

  .privacy-notice {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 14px 18px;
    border-radius: 14px;
    background: #f0f9ff;
    border: 1px solid #bae6fd;
    color: #0369a1;
    font-size: 0.85rem;
    line-height: 1.6;
  }

  .privacy-notice svg {
    flex-shrink: 0;
    margin-top: 1px;
    color: #0284c7;
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

  .provider-section {
    height: 100%;
    padding: 22px;
    border: 1px solid rgba(255, 255, 255, 0.6);
    border-radius: 20px;
    background: linear-gradient(
      180deg,
      rgba(255, 255, 255, 0.7) 0%,
      rgba(248, 253, 255, 0.5) 100%
    );
    box-shadow: 0 8px 24px -8px rgba(15, 23, 42, 0.05);
    display: grid;
    gap: 12px;
  }

  .provider-title {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 800;
    color: #0f172a;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .required-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 999px;
    background: #fef2f2;
    color: #b91c1c;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border: 1px solid #fca5a5;
  }

  .optional-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 999px;
    background: #ecfeff;
    color: #0f766e;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border: 1px solid #99f6e4;
  }

  .provider-desc {
    margin: 0;
    font-size: 0.86rem;
    color: var(--text-muted);
  }

  .provider-link {
    display: inline-flex;
    align-items: center;
    margin-left: 8px;
    color: #0369a1;
    font-weight: 700;
    text-decoration: none;
  }

  .provider-link:hover {
    text-decoration: underline;
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
    font-family: 'SFMono-Regular', Menlo, Monaco, Consolas, monospace;
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
    transition:
      border-color 0.2s ease,
      box-shadow 0.2s ease;
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

  .template-editor {
    width: 100%;
    min-height: 300px;
    resize: vertical;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.92);
    border-radius: 14px;
    padding: 14px 16px;
    color: var(--text-main);
    font-size: 0.92rem;
    line-height: 1.65;
    font-family:
      'SFMono-Regular', Menlo, Monaco, Consolas, 'Liberation Mono',
      'Courier New', monospace;
    transition:
      border-color 0.2s ease,
      box-shadow 0.2s ease;
  }

  .template-editor:focus {
    outline: none;
    border-color: #22d3ee;
    box-shadow: 0 0 0 4px rgba(34, 211, 238, 0.16);
  }

  .actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .clear-button {
    margin-top: 12px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    border-radius: 16px;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    min-height: 52px;
    padding: 0 24px;
    border: 1px solid #fecaca;
    color: #b91c1c;
    background: #fff1f2;
    transition:
      transform 0.16s ease,
      box-shadow 0.2s ease,
      opacity 0.2s ease;
  }

  .ghost-button {
    margin-top: 12px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    border-radius: 16px;
    font-size: 1rem;
    font-weight: 700;
    cursor: pointer;
    min-height: 52px;
    padding: 0 24px;
    border: 1px solid #bae6fd;
    color: #0369a1;
    background: #f0f9ff;
    transition:
      transform 0.16s ease,
      box-shadow 0.2s ease,
      opacity 0.2s ease;
  }

  .ghost-button:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 20px rgba(3, 105, 161, 0.1);
  }

  .ghost-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
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

    .provider-grid {
      grid-template-columns: 1fr;
    }

    .provider-section {
      padding: 18px;
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
