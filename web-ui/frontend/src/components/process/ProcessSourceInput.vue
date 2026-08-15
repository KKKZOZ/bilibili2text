<script setup>
  import {
    CircleHelp,
    FileAudio2,
    FileVideo2,
    Link2,
    Minus,
    Plus
  } from 'lucide-vue-next'
  import ToggleSwitch from '../common/ToggleSwitch.vue'

  const props = defineProps({
    inputMode: { type: String, required: true },
    url: { type: String, required: true },
    allowUpload: Boolean,
    isOpenPublic: Boolean,
    disabled: Boolean,
    uploadAccept: { type: String, required: true },
    preferBilibiliSubtitle: Boolean,
    includeComments: Boolean,
    downloadAllComments: Boolean,
    commentLimit: { type: Number, default: 200 }
  })

  const emit = defineEmits([
    'update:inputMode',
    'update:url',
    'update:preferBilibiliSubtitle',
    'update:includeComments',
    'update:downloadAllComments',
    'update:commentLimit',
    'fileChange'
  ])

  const setCommentLimit = (value) => {
    const parsed = Number(value)
    emit(
      'update:commentLimit',
      Number.isFinite(parsed)
        ? Math.min(1000, Math.max(1, Math.floor(parsed)))
        : 200
    )
  }
  const adjustCommentLimit = (delta) =>
    setCommentLimit(props.commentLimit + delta)
</script>

<template>
  <div class="process-source-input">
    <div class="input-mode-tabs">
      <button
        type="button"
        class="input-mode-button"
        :class="{ active: inputMode !== 'upload' }"
        :disabled="disabled"
        @click="emit('update:inputMode', 'url')"
      >
        <Link2 :size="15" />
        <span>链接 / BV</span>
      </button>
      <button
        v-if="allowUpload"
        type="button"
        class="input-mode-button"
        :class="{ active: inputMode === 'upload' }"
        :disabled="disabled"
        @click="emit('update:inputMode', 'upload')"
      >
        <FileVideo2 v-if="isOpenPublic" :size="15" />
        <FileAudio2 v-else :size="15" />
        <span>{{ isOpenPublic ? '上传音频 / 视频' : '上传音频' }}</span>
      </button>
    </div>

    <template v-if="inputMode !== 'upload'">
      <label for="video-url">视频/播客 URL</label>
      <div class="input-row">
        <Link2 :size="18" />
        <input
          id="video-url"
          :value="url"
          type="text"
          placeholder="支持 Bilibili、小宇宙 FM、喜马拉雅播客链接..."
          @input="emit('update:url', $event.target.value)"
        />
      </div>
      <div class="input-example">
        <span>示例：</span>
        <a
          href="https://www.bilibili.com/video/BV1R9i4BoE7H"
          target="_blank"
          rel="noopener noreferrer"
        >
          https://www.bilibili.com/video/BV1R9i4BoE7H
        </a>
        <a
          href="https://www.xiaoyuzhoufm.com/episode/6a0a7365e1eb34a93997ffa2"
          target="_blank"
          rel="noopener noreferrer"
        >
          https://www.xiaoyuzhoufm.com/episode/6a0a7365e1eb34a93997ffa2
        </a>
        <span>支持 Bilibili / 小宇宙 / 喜马拉雅链接，自动下载音频并转录</span>
      </div>
      <div class="option-toggle-row">
        <ToggleSwitch
          id="prefer-bilibili-subtitle"
          :model-value="preferBilibiliSubtitle"
          label="优先使用 B 站字幕"
          @update:model-value="emit('update:preferBilibiliSubtitle', $event)"
        />
        <span class="option-help">
          <button
            type="button"
            class="option-help-trigger"
            aria-label="查看优先使用 B 站字幕说明"
            aria-describedby="bilibili-subtitle-help-tooltip"
          >
            <CircleHelp :size="15" aria-hidden="true" />
          </button>
          <span
            id="bilibili-subtitle-help-tooltip"
            class="option-help-tooltip"
            role="tooltip"
          >
            仅对 B
            站视频生效。开启后会优先读取视频已有字幕，跳过音频转文字步骤；没有可用字幕或读取失败时会自动回退到音频转录。
          </span>
        </span>
      </div>
      <div class="comments-field">
        <div class="option-toggle-row">
          <ToggleSwitch
            id="include-comments"
            :model-value="includeComments"
            label="总结精选评论"
            compact
            @update:model-value="emit('update:includeComments', $event)"
          />
          <span class="option-help">
            <button
              type="button"
              class="option-help-trigger"
              aria-label="查看精选评论下载说明"
              aria-describedby="comments-help-tooltip"
            >
              <CircleHelp :size="15" aria-hidden="true" />
            </button>
            <span
              id="comments-help-tooltip"
              class="option-help-tooltip"
              role="tooltip"
            >
              支持 B 站和小宇宙。默认按热门排序下载前 200
              条主评论，每条主评论的全部子评论都会下载。
            </span>
          </span>
        </div>
        <div v-if="includeComments" class="comments-options">
          <span class="comments-options-label">主评论数量</span>
          <div
            class="comment-range-segments"
            role="group"
            aria-label="主评论下载范围"
          >
            <button
              type="button"
              class="comment-range-segment"
              :class="{ active: !downloadAllComments }"
              @click="emit('update:downloadAllComments', false)"
            >
              指定数量
            </button>
            <button
              type="button"
              class="comment-range-segment"
              :class="{ active: downloadAllComments }"
              @click="emit('update:downloadAllComments', true)"
            >
              全部
            </button>
          </div>
          <div v-if="!downloadAllComments" class="comment-limit-stepper">
            <button
              type="button"
              aria-label="减少主评论数量"
              @click="adjustCommentLimit(-10)"
            >
              <Minus :size="15" />
            </button>
            <input
              :value="commentLimit"
              type="number"
              min="1"
              max="1000"
              aria-label="主评论数量"
              @change="setCommentLimit($event.target.value)"
            />
            <span>条</span>
            <button
              type="button"
              aria-label="增加主评论数量"
              @click="adjustCommentLimit(10)"
            >
              <Plus :size="15" />
            </button>
          </div>
        </div>
      </div>
    </template>

    <template v-else>
      <label for="audio-file">
        {{
          isOpenPublic ? '音频或视频文件' : '音频文件（文件名必须包含 BV 号）'
        }}
      </label>
      <div class="upload-row">
        <input
          id="audio-file"
          type="file"
          :accept="uploadAccept"
          @change="emit('fileChange', $event)"
        />
      </div>
      <p class="input-example">
        <template v-if="isOpenPublic">
          上传结果不会进入历史记录，仅能通过当前任务链接访问，并会在完成后 2
          小时自动删除。
        </template>
        <template v-else>
          文件名必须符合 <code>BV号_视频标题.xxx</code>，例如
          <code>BV1R9i4BoE7H_视频标题.m4a</code>
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
  .process-source-input {
    display: grid;
    gap: 18px;
  }

  label {
    color: var(--text-soft);
    font-size: 0.9rem;
    font-weight: 700;
  }

  .input-mode-tabs {
    display: inline-flex;
    gap: 6px;
    padding: 6px;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: rgba(248, 250, 252, 0.7);
  }

  .input-mode-button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 38px;
    padding: 0 16px;
    border: none;
    border-radius: 10px;
    background: transparent;
    color: #475569;
    font-size: 0.9rem;
    font-weight: 700;
    cursor: pointer;
  }

  .input-mode-button.active {
    background: linear-gradient(135deg, #0ea5e9, #14b8a6);
    color: #fff;
    box-shadow: 0 2px 8px rgba(14, 165, 233, 0.25);
  }

  .input-mode-button:disabled {
    cursor: not-allowed;
    opacity: 0.65;
  }

  .input-row,
  .upload-row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 52px;
    padding: 0 16px;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.7);
  }

  .input-row:focus-within {
    border-color: #38bdf8;
    background: #fff;
    box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.15);
  }

  .input-row svg {
    flex: 0 0 auto;
    color: #64748b;
  }

  .input-row input,
  .upload-row input {
    width: 100%;
    border: none;
    outline: none;
    background: transparent;
    color: var(--text-main);
    font-size: 1rem;
  }

  .input-example {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin: -4px 0 4px;
    color: var(--text-muted);
    font-size: 0.84rem;
    line-height: 1.5;
  }

  .input-example a {
    color: var(--brand-strong);
    text-decoration: none;
    word-break: break-all;
  }

  .option-toggle-row {
    display: flex;
    align-items: center;
    gap: 3px;
  }

  .option-help {
    position: relative;
    display: inline-flex;
  }

  .option-help-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: #64748b;
    cursor: help;
  }

  .option-help-tooltip {
    position: absolute;
    z-index: 40;
    bottom: calc(100% + 8px);
    left: 50%;
    width: min(360px, calc(100vw - 48px));
    padding: 10px 12px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #fff;
    color: #334155;
    font-size: 0.82rem;
    font-weight: 500;
    line-height: 1.55;
    opacity: 0;
    pointer-events: none;
    transform: translate(-50%, 4px);
    transition: 0.16s ease;
  }

  .option-help:hover .option-help-tooltip,
  .option-help:focus-within .option-help-tooltip {
    opacity: 1;
    transform: translate(-50%, 0);
  }

  .comments-field {
    display: grid;
    gap: 10px;
  }

  .comments-options {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 10px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: rgba(248, 250, 252, 0.78);
  }

  .comments-options-label {
    color: #475569;
    font-size: 0.82rem;
    font-weight: 700;
  }

  .comment-range-segments {
    display: inline-grid;
    grid-template-columns: repeat(2, max-content);
    gap: 2px;
    padding: 3px;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    background: #e2e8f0;
  }

  .comment-range-segment {
    min-height: 30px;
    padding: 0 11px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: #64748b;
    font-size: 0.82rem;
    font-weight: 700;
    cursor: pointer;
  }

  .comment-range-segment.active {
    background: #fff;
    color: #0f766e;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
  }

  .comment-limit-stepper {
    display: inline-flex;
    align-items: center;
    height: 38px;
    overflow: hidden;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    background: #fff;
  }

  .comment-limit-stepper button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 100%;
    padding: 0;
    border: 0;
    background: #f8fafc;
    color: #64748b;
    cursor: pointer;
  }

  .comment-limit-stepper input {
    width: 58px;
    height: 100%;
    border: 0;
    outline: 0;
    text-align: right;
  }

  .comment-limit-stepper span {
    padding-right: 8px;
    color: #64748b;
    font-size: 0.78rem;
  }

  @media (max-width: 640px) {
    .input-mode-tabs {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      width: 100%;
    }

    .input-mode-button {
      justify-content: center;
      padding: 0 12px;
    }

    .comments-options-label {
      width: 100%;
    }
  }
</style>
