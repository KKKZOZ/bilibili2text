export class ApiError extends Error {
  constructor(message, { status = 0, data = null, cause } = {}) {
    super(message, cause ? { cause } : undefined)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

const buildRequestOptions = (options) => {
  const { json, headers, ...requestOptions } = options
  if (json === undefined) {
    return { headers, ...requestOptions }
  }
  return {
    ...requestOptions,
    headers: {
      'Content-Type': 'application/json',
      ...headers
    },
    body: JSON.stringify(json)
  }
}

const fetchResponse = async (url, options, fallbackMessage) => {
  try {
    return await fetch(url, buildRequestOptions(options))
  } catch (cause) {
    throw new ApiError(`${fallbackMessage}：无法连接到服务`, { cause })
  }
}

const parseJson = async (response, fallbackMessage) => {
  const raw = await response.text()
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw)
  } catch (cause) {
    throw new ApiError(
      `${fallbackMessage}（服务返回了非 JSON 响应，HTTP ${response.status}）`,
      { status: response.status, cause }
    )
  }
}

const errorMessage = (response, data, fallbackMessage) => {
  const detail = data?.detail || data?.message
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim()
  }
  return `${fallbackMessage}（HTTP ${response.status}）`
}

export const requestJson = async (
  url,
  options = {},
  fallbackMessage = '请求失败'
) => {
  const response = await fetchResponse(url, options, fallbackMessage)
  const data = await parseJson(response, fallbackMessage)
  if (!response.ok) {
    throw new ApiError(errorMessage(response, data, fallbackMessage), {
      status: response.status,
      data
    })
  }
  if (!data || typeof data !== 'object') {
    throw new ApiError(`${fallbackMessage}（服务返回空响应）`, {
      status: response.status,
      data
    })
  }
  return data
}

export const requestText = async (
  url,
  options = {},
  fallbackMessage = '请求失败'
) => {
  const response = await fetchResponse(url, options, fallbackMessage)
  const text = await response.text()
  if (!response.ok) {
    throw new ApiError(`${fallbackMessage}（HTTP ${response.status}）`, {
      status: response.status
    })
  }
  return text
}

export const requestStream = async (
  url,
  options = {},
  fallbackMessage = '请求失败'
) => {
  const response = await fetchResponse(url, options, fallbackMessage)
  if (!response.ok) {
    const data = await parseJson(response, fallbackMessage)
    throw new ApiError(errorMessage(response, data, fallbackMessage), {
      status: response.status,
      data
    })
  }
  if (!response.body) {
    throw new ApiError(`${fallbackMessage}（服务未返回数据流）`, {
      status: response.status
    })
  }
  return response.body
}
