/**
 * Composable function for file conversion
 */
import { ref } from 'vue'

export function useConversion() {
  const convertingItems = ref(new Set())
  const conversionError = ref('')

  const convertAndDownload = async (
    downloadId,
    filename,
    targetFormat,
    extraPayload = {}
  ) => {
    const renderMode = extraPayload?.render_mode || ''
    const key = `${downloadId}-${targetFormat}-${renderMode}`
    if (convertingItems.value.has(key)) {
      return
    }

    convertingItems.value.add(key)
    conversionError.value = ''

    try {
      const resp = await fetch('/api/convert', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          download_id: downloadId,
          target_format: targetFormat,
          ...extraPayload
        })
      })
      const data = await resp.json()

      if (!resp.ok) {
        throw new Error(data.detail || '转换失败')
      }

      // Automatically download the converted file
      download(data.download_url, data.filename)
    } catch (err) {
      conversionError.value = err instanceof Error ? err.message : '转换失败'
    } finally {
      convertingItems.value.delete(key)
    }
  }

  const isConverting = (downloadId, targetFormat, extraPayload = {}) => {
    const renderMode = extraPayload?.render_mode || ''
    return convertingItems.value.has(
      `${downloadId}-${targetFormat}-${renderMode}`
    )
  }

  const download = (url, filename) => {
    if (!url) {
      return
    }

    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename || 'output.md'
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
  }

  return {
    convertingItems,
    conversionError,
    convertAndDownload,
    isConverting,
    download
  }
}
