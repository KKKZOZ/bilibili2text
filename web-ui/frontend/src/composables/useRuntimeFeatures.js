import { computed, readonly, ref } from 'vue'
import { runtimeApi } from '../api'

const defaultFeatures = () => ({
  mode: 'default',
  allow_upload_audio: true,
  allow_delete: true,
  requires_user_api_key: false,
  api_key_configured: true
})

const runtimeFeatures = ref(defaultFeatures())
const runtimeError = ref('')
const isLoadingRuntime = ref(false)
const isOpenPublic = computed(
  () => runtimeFeatures.value.mode === 'open-public'
)

const loadRuntimeFeatures = async () => {
  isLoadingRuntime.value = true
  runtimeError.value = ''
  try {
    const data = await runtimeApi.getFeatures()
    runtimeFeatures.value = {
      mode: data.mode === 'open-public' ? 'open-public' : 'default',
      allow_upload_audio: Boolean(data.allow_upload_audio),
      allow_delete: Boolean(data.allow_delete),
      requires_user_api_key: Boolean(data.requires_user_api_key),
      api_key_configured: Boolean(data.api_key_configured)
    }
  } catch (error) {
    console.error(error)
    runtimeFeatures.value = defaultFeatures()
    runtimeError.value =
      error instanceof Error ? error.message : '获取运行时配置失败'
  } finally {
    isLoadingRuntime.value = false
  }
}

export function useRuntimeFeatures() {
  return {
    runtimeFeatures: readonly(runtimeFeatures),
    runtimeError: readonly(runtimeError),
    isLoadingRuntime: readonly(isLoadingRuntime),
    isOpenPublic,
    loadRuntimeFeatures
  }
}
