/**
 * 文件相关的工具函数
 */

export function resolveFileType(filename, kind) {
  const extensionMap = {
    md: 'Markdown',
    markdown: 'Markdown',
    txt: 'TXT',
    pdf: 'PDF',
    json: 'JSON',
    m4a: 'M4A',
    mp3: 'MP3',
    wav: 'WAV',
  };
  const fromKindMap = {
    markdown: 'Markdown',
    text: 'TXT',
    summary: 'Markdown',
    summary_no_table: 'Markdown',
    summary_text: 'TXT',
    summary_table_md: 'Markdown',
    summary_table_pdf: 'PDF',
    json: 'JSON',
    audio: '音频',
  };

  if (typeof filename === 'string') {
    const dotIndex = filename.lastIndexOf('.');
    if (dotIndex >= 0 && dotIndex < filename.length - 1) {
      const ext = filename.slice(dotIndex + 1).toLowerCase();
      if (ext in extensionMap) {
        return extensionMap[ext];
      }
      return ext.toUpperCase();
    }
  }

  return fromKindMap[kind] || '文件';
}

export function inferBvidFromFilename(filename) {
  if (typeof filename !== 'string' || filename.length === 0) {
    return 'BV号';
  }
  const match = filename.match(/BV[0-9A-Za-z]{10}/i);
  return match ? match[0].toUpperCase() : 'BV号';
}

export function inferSummaryPresetFromFilename(filename) {
  if (typeof filename !== 'string' || filename.trim() === '') {
    return 'default';
  }
  const stem = filename.replace(/\.[^.]*$/, '');
  if (/_summary_table$/i.test(stem)) {
    return '';
  }
  const presetMatch = stem.match(/_summary[_-](.+)$/i);
  if (presetMatch && presetMatch[1]) {
    return presetMatch[1];
  }
  if (/_summary$/i.test(stem)) {
    return 'default';
  }
  return 'default';
}

export function buildArtifactDisplayName(artifact, options = {}) {
  const bvid = options.bvid || inferBvidFromFilename(artifact.filename);
  if (artifact.kind === 'summary' || artifact.kind === 'summary_text') {
    return `${bvid}_总结`;
  }
  if (artifact.kind === 'summary_no_table') {
    return `${bvid}_总结_无表格`;
  }
  if (artifact.kind === 'summary_table_md' || artifact.kind === 'summary_table_pdf') {
    return `${bvid}_表格`;
  }
  if (artifact.kind === 'markdown' || artifact.kind === 'text') {
    return `${bvid}_原文`;
  }
  if (artifact.kind === 'json') {
    return `${bvid}_转录`;
  }
  if (artifact.kind === 'audio') {
    return `${bvid}_音频`;
  }
  return `${bvid}_文件`;
}

export function formatTime(isoString) {
  if (!isoString) return '--';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return isoString;
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function bilibiliVideoUrl(bvid) {
  if (typeof bvid !== 'string' || bvid.trim() === '') {
    return 'https://www.bilibili.com/';
  }
  return `https://www.bilibili.com/video/${encodeURIComponent(bvid.trim())}`;
}
