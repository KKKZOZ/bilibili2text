import { ApiError, requestJson, requestStream, requestText } from './client'

const encode = (value) => encodeURIComponent(String(value))

const assertJobStart = (data) => {
  if (typeof data.job_id !== 'string' || !data.job_id) {
    throw new ApiError('提交任务失败（服务未返回有效 job_id）', { data })
  }
  return data
}

const assertConnectionTest = (data) => {
  if (typeof data.content !== 'string' || !data.content.trim()) {
    throw new ApiError('后端测试接口返回了空响应', { data })
  }
  return data
}

export const runtimeApi = {
  getFeatures: () => requestJson('/api/runtime', {}, '获取运行时配置失败')
}

export const summaryApi = {
  getPresets: () =>
    requestJson('/api/summary-presets', {}, '获取总结 presets 失败'),
  getProfiles: () =>
    requestJson('/api/summarize-profiles', {}, '获取总结模型配置失败'),
  generateFancyHtml: (payload) =>
    requestJson(
      '/api/summary/fancy-html',
      { method: 'POST', json: payload },
      '生成 Fancy HTML 失败'
    )
}

export const processApi = {
  getJob: (jobId) =>
    requestJson(`/api/process/${encode(jobId)}`, {}, '获取任务进度失败'),
  startFromUrl: async (payload) =>
    assertJobStart(
      await requestJson(
        '/api/process',
        { method: 'POST', json: payload },
        '提交任务失败'
      )
    ),
  startFromUpload: async (formData) =>
    assertJobStart(
      await requestJson(
        '/api/process/upload',
        { method: 'POST', body: formData },
        '提交任务失败'
      )
    ),
  cancelJob: (jobId) =>
    requestJson(
      `/api/process/${encode(jobId)}/cancel`,
      { method: 'POST' },
      '取消任务失败'
    )
}

export const historyApi = {
  list: (params) =>
    requestJson(`/api/history?${params.toString()}`, {}, '获取历史记录失败'),
  getDetail: (runId) =>
    requestJson(`/api/history/${encode(runId)}`, {}, '获取详情失败'),
  regenerateSummary: (runId, payload) =>
    requestJson(
      `/api/history/${encode(runId)}/regenerate-summary`,
      { method: 'POST', json: payload },
      '重新生成总结失败'
    ),
  deleteRun: (runId) =>
    requestJson(
      `/api/history/${encode(runId)}`,
      { method: 'DELETE' },
      '删除失败'
    ),
  deleteArtifact: (runId, downloadId) =>
    requestJson(
      `/api/history/${encode(runId)}/artifacts/${encode(downloadId)}`,
      { method: 'DELETE' },
      '删除文件失败'
    )
}

export const artifactApi = {
  convert: (payload) =>
    requestJson('/api/convert', { method: 'POST', json: payload }, '转换失败'),
  readText: (url, fallbackMessage = '读取文件失败') =>
    requestText(url, {}, fallbackMessage),
  renderedPreviewUrl: (downloadId, sourceVariant = '') => {
    const params = sourceVariant
      ? `?source_variant=${encodeURIComponent(sourceVariant)}`
      : ''
    return `/api/preview/html/${encode(downloadId)}${params}`
  },
  timelinePreviewUrl: (downloadId) => `/api/preview/txt/${encode(downloadId)}`
}

export const ragApi = {
  getAuthors: () => requestJson('/api/rag/authors', {}, '获取作者列表失败'),
  queryStream: (payload) =>
    requestStream(
      '/api/rag/query-stream',
      { method: 'POST', json: payload },
      '查询失败'
    ),
  getStatus: () => requestJson('/api/rag/status', {}, '获取索引状态失败'),
  indexAll: (force) =>
    requestJson(
      '/api/rag/index-all',
      { method: 'POST', json: { force } },
      '索引失败'
    )
}

export const openPublicApi = {
  testProvider: async (provider, apiKey) =>
    assertConnectionTest(
      await requestJson(
        '/api/open-public/api-key/test',
        { method: 'POST', json: { provider, api_key: apiKey } },
        '测试连接失败'
      )
    ),
  testCustomLlm: async ({ baseUrl, apiKey, model }) =>
    assertConnectionTest(
      await requestJson(
        '/api/open-public/custom-llm/test',
        {
          method: 'POST',
          json: { base_url: baseUrl, api_key: apiKey, model }
        },
        '测试连接失败'
      )
    )
}

export { ApiError }
