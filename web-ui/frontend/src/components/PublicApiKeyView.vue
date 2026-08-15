<script setup>
  import { onMounted, ref, watch } from 'vue'
  import { Shield, Info } from 'lucide-vue-next'
  import { openPublicApi } from '../api'
  import ApiKeyProviderCard from './settings/ApiKeyProviderCard.vue'
  import CustomLlmCard from './settings/CustomLlmCard.vue'
  import SummaryTemplateCard from './settings/SummaryTemplateCard.vue'
  import { usePublicCredentials } from '../composables/usePublicCredentials'
  import { useSummaryConfig } from '../composables/useSummaryConfig'

  const { keys, readValue, writeValue, removeValue, refreshCredentials } =
    usePublicCredentials()
  const { summaryDefaultPromptTemplate } = useSummaryConfig()
  const notifyCredentialsUpdated = () => refreshCredentials({ notify: true })
  const LOCAL_API_KEY_KEY = keys.apiKey
  const LOCAL_DEEPSEEK_API_KEY_KEY = keys.deepseekApiKey
  const LOCAL_CUSTOM_LLM_BASE_URL_KEY = keys.customLlmBaseUrl
  const LOCAL_CUSTOM_LLM_API_KEY_KEY = keys.customLlmApiKey
  const LOCAL_CUSTOM_LLM_MODEL_KEY = keys.customLlmModel
  const LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY = keys.summaryTemplate

  // Aliyun key state
  const aliyunKeyInput = ref('')
  const aliyunConfigured = ref(false)
  const aliyunMaskedKey = ref('')
  const aliyunError = ref('')
  const aliyunSuccess = ref('')
  const isTestingAliyun = ref(false)
  const aliyunTestPassed = ref(false)

  // DeepSeek key state
  const deepseekKeyInput = ref('')
  const deepseekConfigured = ref(false)
  const deepseekMaskedKey = ref('')
  const deepseekError = ref('')
  const deepseekSuccess = ref('')
  const isTestingDeepseek = ref(false)
  const deepseekTestPassed = ref(false)

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
  const customLlmTestPassed = ref(false)

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
      const aliyunKey = readValue(LOCAL_API_KEY_KEY)
      aliyunConfigured.value = aliyunKey.length > 0
      aliyunMaskedKey.value = aliyunKey ? maskKey(aliyunKey) : ''

      const dsKey = readValue(LOCAL_DEEPSEEK_API_KEY_KEY)
      deepseekConfigured.value = dsKey.length > 0
      deepseekMaskedKey.value = dsKey ? maskKey(dsKey) : ''

      const customBaseUrl = readValue(LOCAL_CUSTOM_LLM_BASE_URL_KEY)
      const customApiKey = readValue(LOCAL_CUSTOM_LLM_API_KEY_KEY)
      const customModel = readValue(LOCAL_CUSTOM_LLM_MODEL_KEY)
      customLlmConfigured.value = Boolean(
        customBaseUrl && customApiKey && customModel
      )
      customLlmMaskedKey.value = customApiKey ? maskKey(customApiKey) : ''
      customLlmSavedBaseUrl.value = customBaseUrl
      customLlmSavedModel.value = customModel
      customLlmBaseUrlInput.value = customBaseUrl
      customLlmModelInput.value = customModel

      const summaryTemplate = readValue(LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY)
      summaryTemplateConfigured.value = summaryTemplate.length > 0
      summaryTemplateInput.value =
        summaryTemplate || summaryDefaultPromptTemplate.value
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
    return readValue(LOCAL_CUSTOM_LLM_API_KEY_KEY)
  }

  const getSavedProviderApiKey = (storageKey) => readValue(storageKey)

  const testProviderConnection = async ({
    provider,
    label,
    inputValue,
    storageKey,
    setError,
    setSuccess,
    setTesting,
    setTestPassed
  }) => {
    const apiKey = inputValue.trim() || getSavedProviderApiKey(storageKey)
    if (!apiKey) {
      setError('请输入 API Key，或先保存已有 Key')
      setSuccess('')
      setTestPassed(false)
      return
    }
    const validationError = validateKey(apiKey, label)
    if (validationError) {
      setError(validationError)
      setSuccess('')
      setTestPassed(false)
      return
    }
    setError('')
    setSuccess('')
    setTestPassed(false)
    setTesting(true)
    try {
      await openPublicApi.testProvider(provider, apiKey)
      setTestPassed(true)
    } catch (err) {
      setTestPassed(false)
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
      customLlmTestPassed.value = false
      return
    }
    customLlmError.value = ''
    customLlmSuccess.value = ''
    try {
      writeValue(LOCAL_CUSTOM_LLM_BASE_URL_KEY, baseUrl)
      writeValue(LOCAL_CUSTOM_LLM_API_KEY_KEY, apiKey)
      writeValue(LOCAL_CUSTOM_LLM_MODEL_KEY, model)
      customLlmConfigured.value = true
      customLlmMaskedKey.value = maskKey(apiKey)
      customLlmSavedBaseUrl.value = baseUrl
      customLlmSavedModel.value = model
      customLlmApiKeyInput.value = ''
      customLlmSuccess.value =
        '自定义 LLM 已更新。后续总结、知识库问答和 Fancy HTML 将优先使用该模型。'
      notifyCredentialsUpdated()
    } catch {
      customLlmError.value = '保存失败，请检查浏览器存储权限'
    }
  }

  const clearCustomLlm = () => {
    customLlmError.value = ''
    customLlmSuccess.value = ''
    try {
      removeValue(LOCAL_CUSTOM_LLM_BASE_URL_KEY)
      removeValue(LOCAL_CUSTOM_LLM_API_KEY_KEY)
      removeValue(LOCAL_CUSTOM_LLM_MODEL_KEY)
      customLlmConfigured.value = false
      customLlmMaskedKey.value = ''
      customLlmSavedBaseUrl.value = ''
      customLlmSavedModel.value = ''
      customLlmBaseUrlInput.value = ''
      customLlmApiKeyInput.value = ''
      customLlmModelInput.value = ''
      customLlmSuccess.value =
        '自定义 LLM 已清除。LLM 功能将回退使用 DeepSeek 或阿里云。'
      notifyCredentialsUpdated()
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
      customLlmTestPassed.value = false
      return
    }
    customLlmError.value = ''
    customLlmSuccess.value = ''
    customLlmTestPassed.value = false
    isTestingCustomLlm.value = true
    try {
      await openPublicApi.testCustomLlm({
        baseUrl,
        apiKey,
        model
      })
      customLlmTestPassed.value = true
    } catch (err) {
      customLlmTestPassed.value = false
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
      },
      setTestPassed: (value) => {
        aliyunTestPassed.value = value
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
      writeValue(LOCAL_API_KEY_KEY, apiKey)
      aliyunConfigured.value = true
      aliyunMaskedKey.value = maskKey(apiKey)
      aliyunKeyInput.value = ''
      aliyunSuccess.value = '阿里云 API Key 已更新。'
      notifyCredentialsUpdated()
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
      },
      setTestPassed: (value) => {
        deepseekTestPassed.value = value
      }
    })

  const clearAliyunKey = () => {
    aliyunError.value = ''
    aliyunSuccess.value = ''
    try {
      removeValue(LOCAL_API_KEY_KEY)
      aliyunConfigured.value = false
      aliyunMaskedKey.value = ''
      aliyunSuccess.value = '阿里云 API Key 已清除。'
      notifyCredentialsUpdated()
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
      writeValue(LOCAL_DEEPSEEK_API_KEY_KEY, apiKey)
      deepseekConfigured.value = true
      deepseekMaskedKey.value = maskKey(apiKey)
      deepseekKeyInput.value = ''
      deepseekSuccess.value =
        'DeepSeek API Key 已更新。后续 LLM 总结、知识库问答和 Fancy HTML 将使用该 Key。'
      notifyCredentialsUpdated()
    } catch {
      deepseekError.value = '保存失败，请检查浏览器存储权限'
    }
  }

  const clearDeepseekKey = () => {
    deepseekError.value = ''
    deepseekSuccess.value = ''
    try {
      removeValue(LOCAL_DEEPSEEK_API_KEY_KEY)
      deepseekConfigured.value = false
      deepseekMaskedKey.value = ''
      deepseekSuccess.value =
        'DeepSeek API Key 已清除。LLM 功能将回退使用阿里云。'
      notifyCredentialsUpdated()
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
      writeValue(LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY, template.trim())
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
      removeValue(LOCAL_OPEN_PUBLIC_SUMMARY_TEMPLATE_KEY)
      summaryTemplateConfigured.value = false
      summaryTemplateInput.value = summaryDefaultPromptTemplate.value || ''
      summaryTemplateSuccess.value = '自定义总结模板已清除。'
    } catch {
      summaryTemplateError.value = '清除失败，请检查浏览器存储权限'
    }
  }

  const resetSummaryTemplateToDefault = () => {
    summaryTemplateError.value = ''
    summaryTemplateSuccess.value = ''
    summaryTemplateInput.value = summaryDefaultPromptTemplate.value || ''
  }

  onMounted(() => {
    loadStatus()
  })

  watch(summaryDefaultPromptTemplate, (template) => {
    if (
      !summaryTemplateConfigured.value &&
      !summaryTemplateInput.value.trim()
    ) {
      summaryTemplateInput.value = template || ''
    }
  })

  watch(aliyunKeyInput, () => {
    aliyunTestPassed.value = false
  })

  watch(deepseekKeyInput, () => {
    deepseekTestPassed.value = false
  })

  watch(
    [customLlmBaseUrlInput, customLlmModelInput, customLlmApiKeyInput],
    () => {
      customLlmTestPassed.value = false
    }
  )
</script>

<template>
  <section class="settings-layout">
    <article class="panel-settings">
      <header class="settings-header">
        <div class="settings-badge">
          <Shield :size="14" />
          <span>open-public</span>
        </div>
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
        <ApiKeyProviderCard
          v-model="aliyunKeyInput"
          title="阿里云 DashScope"
          field-id="aliyun-api-key"
          placeholder="请输入 sk-... 格式的 API Key"
          :configured="aliyunConfigured"
          :masked-key="aliyunMaskedKey"
          :testing="isTestingAliyun"
          :test-passed="aliyunTestPassed"
          :error="aliyunError"
          :success="aliyunSuccess"
          required
          @save="saveAliyunKey"
          @test="testAliyunConnection"
          @clear="clearAliyunKey"
        >
          <p>
            语音识别（ASR）依赖阿里云，无此 Key 无法提交转录任务。
            <a
              href="https://bailian.console.aliyun.com/cn-beijing/?tab=model#/api-key"
              target="_blank"
              rel="noopener noreferrer"
              >前往阿里云百炼创建 API Key</a
            >
          </p>
        </ApiKeyProviderCard>

        <ApiKeyProviderCard
          v-model="deepseekKeyInput"
          title="DeepSeek"
          field-id="deepseek-api-key"
          placeholder="请输入 sk-... 格式的 API Key"
          :configured="deepseekConfigured"
          :masked-key="deepseekMaskedKey"
          :testing="isTestingDeepseek"
          :test-passed="deepseekTestPassed"
          :error="deepseekError"
          :success="deepseekSuccess"
          @save="saveDeepseekKey"
          @test="testDeepseekConnection"
          @clear="clearDeepseekKey"
        >
          <p>
            配置后可用于 LLM 总结、知识库问答和 Fancy HTML。
            <a
              href="https://platform.deepseek.com/api_keys"
              target="_blank"
              rel="noopener noreferrer"
              >前往 DeepSeek 创建 API Key</a
            >
          </p>
          <template #status-note>
            <p v-if="!deepseekConfigured" class="provider-fallback-note">
              未配置时将使用阿里云 Key 进行 LLM 调用。
            </p>
          </template>
        </ApiKeyProviderCard>
      </div>

      <CustomLlmCard
        :configured="customLlmConfigured"
        :masked-key="customLlmMaskedKey"
        :saved-base-url="customLlmSavedBaseUrl"
        :saved-model="customLlmSavedModel"
        :base-url="customLlmBaseUrlInput"
        :model="customLlmModelInput"
        :api-key="customLlmApiKeyInput"
        :testing="isTestingCustomLlm"
        :test-passed="customLlmTestPassed"
        :error="customLlmError"
        :success="customLlmSuccess"
        @update:base-url="customLlmBaseUrlInput = $event"
        @update:model="customLlmModelInput = $event"
        @update:api-key="customLlmApiKeyInput = $event"
        @save="saveCustomLlm"
        @test="testCustomLlmConnection"
        @clear="clearCustomLlm"
      />

      <SummaryTemplateCard
        :configured="summaryTemplateConfigured"
        :model-value="summaryTemplateInput"
        :error="summaryTemplateError"
        :success="summaryTemplateSuccess"
        @update:model-value="summaryTemplateInput = $event"
        @save="saveSummaryTemplate"
        @reset="resetSummaryTemplateToDefault"
        @clear="clearSummaryTemplate"
      />
    </article>
  </section>
</template>

<style scoped>
  .settings-layout {
    max-width: 1120px;
    margin: 0 auto;
  }

  .panel-settings {
    display: grid;
    gap: 16px;
  }

  .settings-header {
    display: grid;
    gap: 8px;
  }

  .settings-header p {
    margin: 0;
  }

  .settings-header p {
    color: var(--text-muted);
    font-size: 0.88rem;
    line-height: 1.65;
  }

  .settings-badge {
    display: inline-flex;
    align-items: center;
    justify-self: start;
    gap: 5px;
    padding: 4px 8px;
    border-radius: 5px;
    background: var(--brand-soft);
    color: var(--brand-strong);
    font-size: 0.72rem;
    font-weight: 700;
  }

  .privacy-notice {
    display: flex;
    align-items: flex-start;
    gap: 9px;
    padding: 12px 14px;
    border: 1px solid #bfdbfe;
    border-radius: 8px;
    background: #f0f9ff;
    color: #075985;
    font-size: 0.8rem;
    line-height: 1.55;
  }

  .privacy-notice svg {
    flex: 0 0 auto;
    margin-top: 2px;
  }

  .provider-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-rows: repeat(8, auto);
    column-gap: 18px;
    row-gap: 0;
  }

  .provider-fallback-note {
    margin: 0 0 12px;
    color: var(--text-muted);
    font-size: 0.8rem;
  }

  @media (max-width: 900px) {
    .provider-grid {
      grid-template-columns: 1fr;
      grid-template-rows: none;
      row-gap: 18px;
    }
  }
</style>
