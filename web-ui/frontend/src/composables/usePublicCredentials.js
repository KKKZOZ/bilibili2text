import { readonly, ref } from 'vue'

export const PUBLIC_CREDENTIAL_KEYS = Object.freeze({
  apiKey: 'b2t.public-api-key',
  deepseekApiKey: 'b2t.public-deepseek-api-key',
  customLlmBaseUrl: 'b2t.public-custom-llm-base-url',
  customLlmApiKey: 'b2t.public-custom-llm-api-key',
  customLlmModel: 'b2t.public-custom-llm-model',
  summaryTemplate: 'b2t.open-public-summary-template'
})

export const CUSTOM_LLM_PROFILE_NAME = 'open_public_custom_llm'

const apiKeyConfigured = ref(true)
const deepseekApiKeyConfigured = ref(false)
const customLlmConfigured = ref(false)
const credentialsVersion = ref(0)

const readValue = (key) => {
  try {
    return (window.localStorage.getItem(key) || '').trim()
  } catch {
    return ''
  }
}

const writeValue = (key, value) => {
  window.localStorage.setItem(key, value)
}

const removeValue = (key) => {
  window.localStorage.removeItem(key)
}

const getCustomLlmConfig = () => ({
  baseUrl: readValue(PUBLIC_CREDENTIAL_KEYS.customLlmBaseUrl),
  apiKey: readValue(PUBLIC_CREDENTIAL_KEYS.customLlmApiKey),
  model: readValue(PUBLIC_CREDENTIAL_KEYS.customLlmModel)
})

const refreshCredentials = ({ notify = false } = {}) => {
  const customLlm = getCustomLlmConfig()
  apiKeyConfigured.value = Boolean(readValue(PUBLIC_CREDENTIAL_KEYS.apiKey))
  deepseekApiKeyConfigured.value = Boolean(
    readValue(PUBLIC_CREDENTIAL_KEYS.deepseekApiKey)
  )
  customLlmConfigured.value = Boolean(
    customLlm.baseUrl && customLlm.apiKey && customLlm.model
  )
  if (notify) {
    credentialsVersion.value += 1
  }
}

const getCustomLlmPayload = (enabled = true) => {
  if (!enabled) {
    return {
      custom_llm_base_url: null,
      custom_llm_api_key: null,
      custom_llm_model: null
    }
  }
  const customLlm = getCustomLlmConfig()
  return {
    custom_llm_base_url: customLlm.baseUrl || null,
    custom_llm_api_key: customLlm.apiKey || null,
    custom_llm_model: customLlm.model || null
  }
}

const getCustomLlmProfile = () => {
  const customLlm = getCustomLlmConfig()
  if (!customLlm.baseUrl || !customLlm.apiKey || !customLlm.model) {
    return null
  }
  return {
    name: CUSTOM_LLM_PROFILE_NAME,
    provider: 'openai_compatible',
    model: customLlm.model,
    api_base: customLlm.baseUrl
  }
}

const appendCustomLlmFormData = (formData, enabled = true) => {
  if (!enabled) return
  const customLlm = getCustomLlmConfig()
  if (!customLlm.baseUrl || !customLlm.apiKey || !customLlm.model) return
  formData.append('custom_llm_base_url', customLlm.baseUrl)
  formData.append('custom_llm_api_key', customLlm.apiKey)
  formData.append('custom_llm_model', customLlm.model)
}

export function usePublicCredentials() {
  return {
    keys: PUBLIC_CREDENTIAL_KEYS,
    apiKeyConfigured: readonly(apiKeyConfigured),
    deepseekApiKeyConfigured: readonly(deepseekApiKeyConfigured),
    customLlmConfigured: readonly(customLlmConfigured),
    credentialsVersion: readonly(credentialsVersion),
    readValue,
    writeValue,
    removeValue,
    refreshCredentials,
    getApiKey: () => readValue(PUBLIC_CREDENTIAL_KEYS.apiKey),
    getDeepseekApiKey: () => readValue(PUBLIC_CREDENTIAL_KEYS.deepseekApiKey),
    getSummaryTemplate: (fallback = '') =>
      readValue(PUBLIC_CREDENTIAL_KEYS.summaryTemplate) || fallback,
    getCustomLlmConfig,
    getCustomLlmPayload,
    getCustomLlmProfile,
    appendCustomLlmFormData
  }
}
