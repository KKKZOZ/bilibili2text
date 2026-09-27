import { afterEach, expect, mock, test } from 'bun:test'
import { requestJson, requestStream, subscribeSse } from './client'
import { apiUrl, artifactApi } from './index'
import { useConversion } from '../composables/useConversion'

const originalFetch = globalThis.fetch
const originalWindow = globalThis.window
const originalDocument = globalThis.document
const originalBase = process.env.VITE_API_BASE_URL

afterEach(() => {
  globalThis.fetch = originalFetch
  globalThis.window = originalWindow
  globalThis.document = originalDocument
  if (originalBase === undefined) delete process.env.VITE_API_BASE_URL
  else process.env.VITE_API_BASE_URL = originalBase
})

test('local proxy URLs and absolute artifact URLs stay intact', () => {
  expect(apiUrl('/api/health', '')).toBe('/api/health')
  expect(apiUrl('https://storage.example/file', 'https://api.example')).toBe(
    'https://storage.example/file'
  )
})

test('JSON, uploads and streamed responses use the Tunnel origin', async () => {
  process.env.VITE_API_BASE_URL = 'https://api.example.com/'
  const fetch = mock(async () => Response.json({ ok: true }))
  globalThis.fetch = fetch
  await requestJson('/api/process', { method: 'POST', json: { url: 'video' } })
  expect(fetch.mock.calls[0][0]).toBe('https://api.example.com/api/process')
  expect(fetch.mock.calls[0][1].headers['Content-Type']).toBe(
    'application/json'
  )
  const body = new FormData()
  body.append('file', new Blob(['audio']), 'audio.wav')
  await requestJson('/api/process/upload', { method: 'POST', body })
  expect(fetch.mock.calls[1][0]).toBe(
    'https://api.example.com/api/process/upload'
  )
  expect(fetch.mock.calls[1][1].body).toBe(body)
  expect(fetch.mock.calls[1][1].headers).toBeUndefined()
  await requestStream('/api/rag/query-stream', { method: 'POST' })
  expect(fetch.mock.calls[2][0]).toBe(
    'https://api.example.com/api/rag/query-stream'
  )
})

test('HTML preview stays on frontend while API requests use the Tunnel origin', () => {
  process.env.VITE_API_BASE_URL = 'https://api.example.com'
  const close = mock(() => {})
  let eventUrl
  globalThis.window = {
    EventSource: class {
      constructor(url) {
        eventUrl = url
      }
      addEventListener() {}
      close = close
    }
  }
  const stop = subscribeSse({
    url: '/api/jobs/events?job_id=one',
    eventName: 'job'
  })
  expect(eventUrl).toBe('https://api.example.com/api/jobs/events?job_id=one')
  stop()
  expect(close).toHaveBeenCalledTimes(1)
  expect(artifactApi.renderedPreviewUrl('one', 'summary_no_table')).toBe(
    '#/preview/html/one?source_variant=summary_no_table'
  )
  expect(artifactApi.renderedPreviewSourceUrl('one', 'summary_no_table')).toBe(
    'https://api.example.com/api/preview/html/one?source_variant=summary_no_table'
  )
  expect(artifactApi.timelinePreviewUrl('one')).toBe(
    'https://api.example.com/api/preview/txt/one'
  )
  const anchor = { click: mock(() => {}) }
  globalThis.document = {
    createElement: () => anchor,
    body: { appendChild: () => {}, removeChild: () => {} }
  }
  useConversion().download('/api/download/one', 'output.md')
  expect(anchor.href).toBe('https://api.example.com/api/download/one')
  expect(anchor.click).toHaveBeenCalledTimes(1)
})
