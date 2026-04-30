import MarkdownIt from 'markdown-it'

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

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true
})

const defaultLinkOpen =
  md.renderer.rules.link_open ||
  function renderLinkOpen(tokens, idx, options, env, self) {
    return self.renderToken(tokens, idx, options)
  }

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

function replaceCitationRefs(html) {
  return html.replace(
    /\[(\d+)\]/g,
    '<span class="citation-ref" data-target="source-$1">[$1]</span>'
  )
}

export function renderMarkdown(markdown) {
  const source = String(markdown || '').replace(/\r\n/g, '\n')
  return replaceCitationRefs(md.render(source))
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
