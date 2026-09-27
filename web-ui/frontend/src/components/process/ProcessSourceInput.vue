<script setup>
  import { ref } from 'vue'
  import { FileAudio2, FileVideo2, Link2, Upload } from 'lucide-vue-next'

  defineProps({
    inputMode: { type: String, required: true },
    url: { type: String, required: true },
    allowUpload: Boolean,
    isOpenPublic: Boolean,
    disabled: Boolean,
    uploadAccept: { type: String, required: true }
  })

  const emit = defineEmits(['update:inputMode', 'update:url', 'fileChange'])
  const selectedFilename = ref('')

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
        <span>B 站视频默认优先读取原生字幕，无可用字幕时使用音频转录</span>
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
  }
</style>
