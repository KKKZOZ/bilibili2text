function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderInline(text) {
  let html = escapeHtml(text)
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  )
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>')
  html = html.replace(
    /\[(\d+)\]/g,
    '<span class="citation-ref" data-target="source-$1">[$1]</span>'
  )
  html = html.replace(/\n/g, '<br />')
  return html
}

function isTableSeparator(line) {
  return /^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(line)
}

function splitTableRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

export function renderMarkdown(markdown) {
  const source = String(markdown || '').replace(/\r\n/g, '\n')
  const lines = source.split('\n')
  const blocks = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    if (trimmed.startsWith('```')) {
      const codeLines = []
      i += 1
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i])
        i += 1
      }
      if (i < lines.length) i += 1
      blocks.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
      continue
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      const level = heading[1].length
      blocks.push(`<h${level}>${renderInline(heading[2])}</h${level}>`)
      i += 1
      continue
    }

    if (
      trimmed.includes('|') &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1])
    ) {
      const headerCells = splitTableRow(lines[i])
      i += 2
      const bodyRows = []
      while (i < lines.length && lines[i].trim().includes('|')) {
        bodyRows.push(splitTableRow(lines[i]))
        i += 1
      }
      blocks.push(
        `<table><thead><tr>${headerCells.map((cell) => `<th>${renderInline(cell)}</th>`).join('')}</tr></thead><tbody>${bodyRows
          .map(
            (row) =>
              `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join('')}</tr>`
          )
          .join('')}</tbody></table>`
      )
      continue
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''))
        i += 1
      }
      blocks.push(
        `<ol>${items.map((item) => `<li>${renderInline(item.trim())}</li>`).join('')}</ol>`
      )
      continue
    }

    if (/^[-*]\s+/.test(trimmed)) {
      const items = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ''))
        i += 1
      }
      blocks.push(
        `<ul>${items.map((item) => `<li>${renderInline(item.trim())}</li>`).join('')}</ul>`
      )
      continue
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        quoteLines.push(lines[i].replace(/^\s*>\s?/, ''))
        i += 1
      }
      blocks.push(
        `<blockquote>${quoteLines.map((item) => `<p>${renderInline(item.trim())}</p>`).join('')}</blockquote>`
      )
      continue
    }

    const paragraphLines = []
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith('```') &&
      !/^(#{1,6})\s+/.test(lines[i].trim()) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i])
    ) {
      paragraphLines.push(lines[i].trim())
      i += 1
    }
    blocks.push(`<p>${renderInline(paragraphLines.join('\n'))}</p>`)
  }

  return blocks.join('\n')
}

export function extractRagReferenceItems(markdown) {
  const content = String(markdown || '')
  const match = content.match(/##\s+参考来源\s*\n+([\s\S]*)$/)
  if (!match) return []
  const section = match[1]
  const tableLines = section
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (
    tableLines.length >= 3 &&
    tableLines[0].includes('|') &&
    isTableSeparator(tableLines[1])
  ) {
    return tableLines
      .slice(2)
      .filter((line) => line.includes('|'))
      .map((line) => {
        const cells = splitTableRow(line)
        const [index, title, bvid, score, text = ''] = cells
        return {
          index: Number(index) || 0,
          title: title || '',
          bvid: bvid && bvid !== '-' ? bvid : '',
          score: Number(String(score || '').replace('%', '')) || 0,
          text: (text || '').replace(/<br\s*\/?>/gi, '\n').trim()
        }
      })
      .filter((item) => item.index > 0)
  }
  const regex =
    /(?:^|\n)\s*(\d+)\.\s+\*\*(.+?)\*\*(?:\s+\((BV[0-9A-Za-z]+)\))?\s+[—-]\s+相关度\s+(\d+)%\s*\n+\s*>\s*(.+?)(?=\n\s*\d+\.\s+\*\*|\n*$)/gs
  const items = []
  for (const part of section.matchAll(regex)) {
    items.push({
      index: Number(part[1]),
      title: part[2] || '',
      bvid: part[3] || '',
      score: Number(part[4]) || 0,
      text: (part[5] || '').trim()
    })
  }
  return items
}
