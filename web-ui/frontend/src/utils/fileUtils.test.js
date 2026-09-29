import { expect, test } from 'bun:test'
import {
  buildArtifactDisplayName,
  inferResourceIdFromFilename,
  resourcePlatformInfo,
  resourceUrl
} from './fileUtils'

test('YouTube resource IDs preserve case and embedded underscores', () => {
  const id = 'youtube_BaW_jenozKc'
  expect(resourcePlatformInfo(id).name).toBe('YouTube')
  expect(resourceUrl(id)).toBe('https://www.youtube.com/watch?v=BaW_jenozKc')
})

test.each([
  ['markdown', '原文'],
  ['summary', '总结'],
  ['summary_no_table', '总结_无表格'],
  ['summary_table_md', '表格'],
  ['summary_timeline', '时间线']
])(
  'YouTube %s labels use the resource ID without a BV placeholder',
  (kind, label) => {
    const artifact = {
      filename: 'youtube_BaW_jenozKc_视频标题_transcription.md',
      kind
    }
    expect(buildArtifactDisplayName(artifact)).toBe(
      `youtube_BaW_jenozKc_${label}`
    )
    expect(
      buildArtifactDisplayName(artifact, { bvid: 'youtube_jNQXAC9IVRw' })
    ).toBe(`youtube_jNQXAC9IVRw_${label}`)
  }
)

test.each([
  'youtube_BaW_jenozKc',
  'xiaoyuzhou_6a0a7365e1eb34a93997ffa2',
  'ximalaya_12345',
  'BV1R9i4BoE7H'
])('artifact filename inference preserves %s', (id) => {
  expect(inferResourceIdFromFilename(`${id}_视频标题_summary.md`)).toBe(id)
})

test('unknown filenames do not masquerade as Bilibili resources', () => {
  expect(
    buildArtifactDisplayName({ filename: 'notes.md', kind: 'markdown' })
  ).toBe('资源_原文')
  expect(inferResourceIdFromFilename('youtube_short.md')).toBe('')
})
