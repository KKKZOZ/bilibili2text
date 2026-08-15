import { readonly, ref, watch } from 'vue'
import { summaryApi } from '../api'
import {
  CUSTOM_LLM_PROFILE_NAME,
  usePublicCredentials
} from './usePublicCredentials'
import { useRuntimeFeatures } from './useRuntimeFeatures'

export const CUSTOM_SUMMARY_PRESET_VALUE = '__user_custom__'

export const formatSummaryProfileLabel = (profile) => {
  if (!profile) return ''
  if (profile.name === CUSTOM_LLM_PROFILE_NAME) {
    return `custom(${profile.model || 'model'})`
  }
  return `${profile.name} (${profile.model})`
}

export const withCustomSummaryPreset = (presets, enabled) => {
  const base = Array.isArray(presets) ? presets : []
  return enabled
    ? [...base, { name: CUSTOM_SUMMARY_PRESET_VALUE, label: '用户自定义' }]
    : base
}

const summaryPresets = ref([])
const summaryDefaultPreset = ref('')
const summaryDefaultPromptTemplate = ref('')
const summaryProfiles = ref([])
const selectedSummaryPreset = ref('')
const selectedSummaryProfile = ref('')
const summaryPresetError = ref('')
const summaryProfileError = ref('')
const isLoadingSummaryPresets = ref(false)
const isLoadingSummaryProfiles = ref(false)
let initialized = false
let initializePromise = null

const { isOpenPublic } = useRuntimeFeatures()
const { credentialsVersion, getCustomLlmProfile } = usePublicCredentials()

const loadSummaryPresets = async () => {
  isLoadingSummaryPresets.value = true
  summaryPresetError.value = ''
  try {
    const data = await summaryApi.getPresets()
    const presets = Array.isArray(data.presets) ? data.presets : []
    summaryPresets.value = presets
    if (presets.length === 0) {
      summaryDefaultPreset.value = ''
      summaryDefaultPromptTemplate.value = ''
      selectedSummaryPreset.value = ''
      return
    }

    const fallback = presets[0].name
    summaryDefaultPreset.value = data.default_preset || fallback
    selectedSummaryPreset.value =
      data.selected_preset || summaryDefaultPreset.value || fallback
    const defaultPreset =
      presets.find((item) => item.name === summaryDefaultPreset.value) ||
      presets.find((item) => item.name === selectedSummaryPreset.value) ||
      presets[0]
    summaryDefaultPromptTemplate.value =
      typeof defaultPreset?.prompt_template === 'string'
        ? defaultPreset.prompt_template
        : ''
  } catch (error) {
    console.error(error)
    summaryPresets.value = []
    summaryDefaultPreset.value = ''
    summaryDefaultPromptTemplate.value = ''
    selectedSummaryPreset.value = ''
    summaryPresetError.value =
      error instanceof Error
        ? `preset 加载失败：${error.message}`
        : 'preset 加载失败，请检查后端服务是否已启动'
  } finally {
    isLoadingSummaryPresets.value = false
  }
}

const loadSummaryProfiles = async () => {
  isLoadingSummaryProfiles.value = true
  summaryProfileError.value = ''
  try {
    const data = await summaryApi.getProfiles()
    const profiles = Array.isArray(data.profiles) ? [...data.profiles] : []
    const customProfile = isOpenPublic.value ? getCustomLlmProfile() : null
    if (customProfile) {
      const existingIndex = profiles.findIndex(
        (profile) => profile.name === customProfile.name
      )
      if (existingIndex >= 0) {
        profiles.splice(existingIndex, 1, customProfile)
      } else {
        profiles.push(customProfile)
      }
    }
    summaryProfiles.value = profiles
    if (profiles.length === 0) {
      selectedSummaryProfile.value = ''
      return
    }

    const fallback = profiles[0].name
    selectedSummaryProfile.value = customProfile
      ? customProfile.name
      : data.selected_profile || data.default_profile || fallback
  } catch (error) {
    console.error(error)
    summaryProfiles.value = []
    selectedSummaryProfile.value = ''
    summaryProfileError.value =
      error instanceof Error
        ? `模型配置加载失败：${error.message}`
        : '模型配置加载失败，请检查后端服务是否已启动'
  } finally {
    isLoadingSummaryProfiles.value = false
  }
}

const initializeSummaryConfig = () => {
  if (!initializePromise) {
    initializePromise = Promise.all([
      loadSummaryProfiles(),
      loadSummaryPresets()
    ]).finally(() => {
      initialized = true
    })
  }
  return initializePromise
}

watch(credentialsVersion, () => {
  if (initialized) {
    void loadSummaryProfiles()
  }
})

export function useSummaryConfig() {
  return {
    summaryPresets: readonly(summaryPresets),
    summaryDefaultPreset: readonly(summaryDefaultPreset),
    summaryDefaultPromptTemplate: readonly(summaryDefaultPromptTemplate),
    summaryProfiles: readonly(summaryProfiles),
    selectedSummaryPreset,
    selectedSummaryProfile,
    summaryPresetError: readonly(summaryPresetError),
    summaryProfileError: readonly(summaryProfileError),
    isLoadingSummaryPresets: readonly(isLoadingSummaryPresets),
    isLoadingSummaryProfiles: readonly(isLoadingSummaryProfiles),
    loadSummaryPresets,
    loadSummaryProfiles,
    initializeSummaryConfig
  }
}
