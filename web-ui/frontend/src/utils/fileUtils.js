/**
 * File-related utility functions
 */

export function resolveFileType(filename, kind) {
  const extensionMap = {
    md: 'Markdown',
    markdown: 'Markdown',
    txt: 'TXT',
    pdf: 'PDF',
    png: 'PNG',
    html: 'HTML',
    json: 'JSON',
    m4a: 'M4A',
    mp3: 'MP3',
    wav: 'WAV'
  }
  const fromKindMap = {
    markdown: 'Markdown',
    text: 'TXT',
    summary: 'Markdown',
    summary_no_table: 'Markdown',
    summary_png: 'PNG',
    summary_no_table_png: 'PNG',
    summary_text: 'TXT',
    summary_timeline: 'TXT',
    summary_fancy_html: 'HTML',
    summary_table_md: 'Markdown',
    summary_table_png: 'PNG',
    summary_table_pdf: 'PDF',
    json: 'JSON',
    audio: '音频',
    rag_answer: 'Markdown'
  }

  if (typeof filename === 'string') {
    const dotIndex = filename.lastIndexOf('.')
    if (dotIndex >= 0 && dotIndex < filename.length - 1) {
      const ext = filename.slice(dotIndex + 1).toLowerCase()
      if (ext in extensionMap) {
        return extensionMap[ext]
      }
      return ext.toUpperCase()
    }
  }

  return fromKindMap[kind] || '文件'
}

export function inferBvidFromFilename(filename) {
  if (typeof filename !== 'string' || filename.length === 0) {
    return 'BV号'
  }
  const match = filename.match(/BV[0-9A-Za-z]{10}/i)
  return match ? match[0].toUpperCase() : 'BV号'
}

export function inferSummaryPresetFromFilename(filename) {
  if (typeof filename !== 'string' || filename.trim() === '') {
    return 'default'
  }
  const stem = filename.replace(/\.[^.]*$/, '')
  if (/_summary_table$/i.test(stem)) {
    return ''
  }
  const presetMatch = stem.match(/_summary[_-](.+)$/i)
  if (presetMatch && presetMatch[1]) {
    return presetMatch[1]
  }
  if (/_summary$/i.test(stem)) {
    return 'default'
  }
  return 'default'
}

export function buildArtifactDisplayName(artifact, options = {}) {
  const bvid = options.bvid || inferBvidFromFilename(artifact.filename)
  const stem = (artifact.filename || '').replace(/\.[^.]*$/, '')
  if (
    artifact.kind === 'summary' ||
    artifact.kind === 'summary_text' ||
    artifact.kind === 'summary_png'
  ) {
    return `${bvid}_总结`
  }
  if (artifact.kind === 'summary_timeline') {
    return `${bvid}_时间线`
  }
  if (
    artifact.kind === 'summary_no_table' ||
    artifact.kind === 'summary_no_table_png'
  ) {
    return `${bvid}_总结_无表格`
  }
  if (artifact.kind === 'summary_fancy_html') {
    if (stem.startsWith('rag_')) {
      const questionPart = stem
        .replace(/^rag_\d{8}_\d{6}_/, '')
        .replace(/_fancy$/i, '')
      if (questionPart) {
        return `${questionPart.replace(/_/g, ' ')} FancyHTML`
      }
      return '知识库查询 FancyHTML'
    }
    return `${bvid}_总结_FancyHTML`
  }
  if (
    artifact.kind === 'summary_table_md' ||
    artifact.kind === 'summary_table_png' ||
    artifact.kind === 'summary_table_pdf'
  ) {
    return `${bvid}_表格`
  }
  if (artifact.kind === 'markdown' || artifact.kind === 'text') {
    return `${bvid}_原文`
  }
  if (artifact.kind === 'json') {
    return `${bvid}_转录`
  }
  if (artifact.kind === 'audio') {
    return `${bvid}_音频`
  }
  if (artifact.kind === 'rag_answer') {
    // filename: rag_YYYYMMDD_HHMMSS_question_text.md — extract question part
    const questionPart = stem.replace(/^rag_\d{8}_\d{6}_/, '')
    if (questionPart) {
      return questionPart.replace(/_/g, ' ')
    }
    return '知识库查询'
  }
  return `${bvid}_文件`
}

export function formatTime(isoString) {
  if (!isoString) return '--'
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return isoString
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

export function bilibiliVideoUrl(bvid, page = null) {
  if (typeof bvid !== 'string' || bvid.trim() === '') {
    return 'https://www.bilibili.com/'
  }
  const baseUrl = `https://www.bilibili.com/video/${encodeURIComponent(bvid.trim())}`
  const pageNumber = Number(page)
  return Number.isInteger(pageNumber) && pageNumber > 1
    ? `${baseUrl}?p=${pageNumber}`
    : baseUrl
}

export function bilibiliVideoLabel(bvid, page = null) {
  const pageNumber = Number(page)
  return Number.isInteger(pageNumber) && pageNumber > 1
    ? `${bvid} · P${pageNumber}`
    : bvid
}

const PLATFORM_RESOURCE_PREFIXES = {
  xiaoyuzhou: {
    name: '小宇宙',
    authorLabel: '主播',
    url: (id) =>
      `https://www.xiaoyuzhoufm.com/episode/${encodeURIComponent(id)}`
  },
  ximalaya: {
    name: '喜马拉雅',
    authorLabel: '主播',
    url: (id) => `https://www.ximalaya.com/sound/${encodeURIComponent(id)}`
  }
}

export function resourcePlatformInfo(resourceId) {
  const raw = typeof resourceId === 'string' ? resourceId.trim() : ''
  if (!raw) {
    return {
      key: 'unknown',
      name: '资源',
      id: '',
      authorLabel: '作者',
      url: null
    }
  }

  for (const [key, config] of Object.entries(PLATFORM_RESOURCE_PREFIXES)) {
    const prefix = `${key}_`
    if (raw.toLowerCase().startsWith(prefix)) {
      const id = raw.slice(prefix.length)
      return {
        key,
        name: config.name,
        id,
        authorLabel: config.authorLabel,
        url: id ? config.url(id) : null
      }
    }
  }

  if (/^BV[0-9A-Za-z]+$/i.test(raw)) {
    return {
      key: 'bilibili',
      name: 'Bilibili',
      id: raw,
      authorLabel: 'UP主',
      url: bilibiliVideoUrl(raw)
    }
  }

  if (/^upload-/i.test(raw)) {
    return {
      key: 'upload',
      name: '上传',
      id: raw.replace(/^upload-/i, ''),
      authorLabel: '作者',
      url: null
    }
  }

  return {
    key: 'unknown',
    name: '资源',
    id: raw,
    authorLabel: '作者',
    url: null
  }
}

export function resourceUrl(resourceId, page = null) {
  const info = resourcePlatformInfo(resourceId)
  if (info.key === 'bilibili') {
    return bilibiliVideoUrl(info.id, page)
  }
  return info.url
}

export function resourceDisplayLabel(resourceId, page = null) {
  const info = resourcePlatformInfo(resourceId)
  if (!info.id) {
    return info.name
  }
  if (info.key === 'bilibili') {
    return bilibiliVideoLabel(info.id, page)
  }
  if (info.key === 'unknown') {
    return info.id
  }
  return `${info.name} ${info.id}`
}

export function resourceAuthorLabel(resourceId) {
  return resourcePlatformInfo(resourceId).authorLabel
}
