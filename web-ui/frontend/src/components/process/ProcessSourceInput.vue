<script setup>
  import { ref } from 'vue'
  import {
    FileAudio2,
    FileVideo2,
    Infinity as InfinityIcon,
    Link2,
    Minus,
    Plus,
    Upload
  } from 'lucide-vue-next'
  import HelpTooltip from '../common/HelpTooltip.vue'
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
  const selectedFilename = ref('')

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
  const onFileChange = (event) => {
    selectedFilename.value = event.target?.files?.[0]?.name || ''
    emit('fileChange', event)
  }
</script>

<template>
  <div class="process-source-input">
    <div class="input-composer">
      <div class="input-mode-tabs" role="group" aria-label="输入方式">
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

      <div v-if="inputMode !== 'upload'" class="input-row">
        <Link2 :size="18" />
        <input
          id="video-url"
          :value="url"
          type="text"
          aria-label="视频或播客 URL"
          placeholder="支持 Bilibili、小宇宙 FM、喜马拉雅播客链接..."
          :disabled="disabled"
          @input="emit('update:url', $event.target.value)"
        />
      </div>
      <div v-else class="upload-row">
        <input
          id="audio-file"
          class="file-input"
          type="file"
          :accept="uploadAccept"
          :aria-label="isOpenPublic ? '选择音频或视频文件' : '选择音频文件'"
          :disabled="disabled"
          @change="onFileChange"
        />
        <label class="file-picker" :class="{ disabled }" for="audio-file">
          <span class="file-picker-action">
            <Upload :size="15" />
            选择文件
          </span>
          <span class="file-picker-name">
            {{
              selectedFilename ||
              (isOpenPublic ? '选择音频或视频文件' : '选择包含 BV 号的音频文件')
            }}
          </span>
        </label>
      </div>
    </div>

    <template v-if="inputMode !== 'upload'">
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
        <HelpTooltip
          id="bilibili-subtitle-help-tooltip"
          label="查看优先使用 B 站字幕说明"
        >
          仅对 B
          站视频生效。开启后会优先读取视频已有字幕，跳过音频转文字步骤；没有可用字幕或读取失败时会自动回退到音频转录。
        </HelpTooltip>
      </div>
      <div class="comments-field">
        <div class="option-toggle-row">
          <ToggleSwitch
            id="include-comments"
            :model-value="includeComments"
            label="总结精选评论"
            @update:model-value="emit('update:includeComments', $event)"
          />
          <HelpTooltip id="comments-help-tooltip" label="查看精选评论下载说明">
            支持 B 站和小宇宙。默认按热门排序下载前 200
            条主评论，每条主评论的全部子评论都会下载。
          </HelpTooltip>
        </div>
        <div v-if="includeComments" class="comments-options">
          <span class="comments-options-label">主评论数量</span>
          <div class="comment-range-control">
            <div
              class="comment-range-segments"
              role="group"
              aria-label="主评论下载范围"
            >
              <button
                type="button"
                class="comment-range-segment"
                :class="{ active: !downloadAllComments }"
                :disabled="disabled"
                @click="emit('update:downloadAllComments', false)"
              >
                指定数量
              </button>
              <button
                type="button"
                class="comment-range-segment"
                :class="{ active: downloadAllComments }"
                :disabled="disabled"
                @click="emit('update:downloadAllComments', true)"
              >
                全部
              </button>
            </div>
            <div v-if="!downloadAllComments" class="comment-limit-stepper">
              <button
                type="button"
                :disabled="disabled"
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
                :disabled="disabled"
                aria-label="主评论数量"
                @change="setCommentLimit($event.target.value)"
              />
              <span>条</span>
              <button
                type="button"
                :disabled="disabled"
                aria-label="增加主评论数量"
                @click="adjustCommentLimit(10)"
              >
                <Plus :size="15" />
              </button>
            </div>
            <div v-else class="comment-all-state">
              <InfinityIcon :size="16" />
              <span>不限数量</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <template v-else>
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

  .input-composer {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 10px;
    align-items: stretch;
  }

  .input-mode-tabs {
    display: inline-flex;
    gap: 4px;
    padding: 4px;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #f1f4f7;
  }

  .input-mode-button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 38px;
    padding: 0 13px;
    border: none;
    border-radius: 5px;
    background: transparent;
    color: #475569;
    font-size: 0.9rem;
    font-weight: 700;
    cursor: pointer;
  }

  .input-mode-button.active {
    background: #fff;
    color: var(--brand-strong);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
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
    min-height: 48px;
    padding: 0 16px;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
  }

  .input-row:focus-within {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px rgba(15, 143, 131, 0.12);
  }

  .input-row svg {
    flex: 0 0 auto;
    color: #64748b;
  }

  .input-row input,
  .upload-row input:not(.file-input) {
    width: 100%;
    border: none;
    outline: none;
    background: transparent;
    color: var(--text-main);
    font-size: 1rem;
  }

  .input-row input:disabled,
  .upload-row input:disabled {
    cursor: not-allowed;
    opacity: 0.65;
  }

  .upload-row {
    padding: 0 7px;
  }

  .file-input {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }

  .file-picker {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-width: 0;
    cursor: pointer;
  }

  .file-picker-action {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 34px;
    padding: 0 11px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #f8fafc;
    color: var(--text-soft);
    font-size: 0.84rem;
    font-weight: 700;
  }

  .file-picker-name {
    min-width: 0;
    overflow: hidden;
    color: var(--text-muted);
    font-size: 0.86rem;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .file-input:focus-visible + .file-picker .file-picker-action {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px rgba(15, 143, 131, 0.12);
  }

  .file-picker.disabled {
    cursor: not-allowed;
    opacity: 0.65;
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

  .comments-field {
    display: grid;
    gap: 10px;
  }

  .comments-options {
    display: grid;
    grid-template-columns: 92px minmax(0, 330px);
    align-items: center;
    gap: 9px 12px;
  }

  .comments-options-label {
    color: var(--text-soft);
    font-size: 0.86rem;
    font-weight: 700;
  }

  .comment-range-control {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 142px;
    align-items: stretch;
    height: 42px;
    overflow: hidden;
    border: 1px solid var(--line);
    border-radius: 7px;
    background: #fff;
  }

  .comment-range-segments {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 2px;
    padding: 3px;
    border-right: 1px solid var(--line);
    background: #f1f4f7;
  }

  .comment-range-segment {
    min-width: 0;
    padding: 0 8px;
    border: 0;
    border-radius: 4px;
    background: transparent;
    color: #64748b;
    font-size: 0.8rem;
    font-weight: 700;
    cursor: pointer;
    white-space: nowrap;
  }

  .comment-range-segment.active {
    background: #fff;
    color: var(--brand-strong);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
  }

  .comment-range-segment:focus-visible,
  .comment-limit-stepper button:focus-visible,
  .comment-limit-stepper input:focus-visible {
    position: relative;
    z-index: 1;
    outline: 2px solid rgba(15, 143, 131, 0.35);
    outline-offset: -2px;
  }

  .comment-range-segment:disabled,
  .comment-limit-stepper button:disabled,
  .comment-limit-stepper input:disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .comment-limit-stepper {
    display: flex;
    align-items: center;
    min-width: 0;
  }

  .comment-limit-stepper button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    color: #64748b;
    cursor: pointer;
  }

  .comment-limit-stepper input {
    min-width: 0;
    width: 58px;
    height: 100%;
    border: 0;
    outline: 0;
    appearance: textfield;
    font: inherit;
    font-variant-numeric: tabular-nums;
    text-align: center;
  }

  .comment-limit-stepper input::-webkit-inner-spin-button,
  .comment-limit-stepper input::-webkit-outer-spin-button {
    margin: 0;
    appearance: none;
  }

  .comment-limit-stepper span {
    padding-right: 3px;
    color: #64748b;
    font-size: 0.78rem;
  }

  .comment-limit-stepper button:hover:not(:disabled) {
    background: var(--brand-soft);
    color: var(--brand-strong);
  }

  .comment-all-state {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    color: #64748b;
    font-size: 0.78rem;
    font-weight: 700;
  }

  .comment-all-state svg {
    color: var(--brand);
  }

  @media (max-width: 640px) {
    .input-composer {
      grid-template-columns: 1fr;
    }

    .input-mode-tabs {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      width: 100%;
    }

    .input-mode-button {
      justify-content: center;
      padding: 0 12px;
    }

    .comments-options {
      grid-template-columns: 1fr;
    }

    .comment-range-control {
      grid-template-columns: minmax(0, 1fr) 136px;
    }
  }
</style>
