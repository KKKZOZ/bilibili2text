<script setup>
  import { onBeforeUnmount, watch } from 'vue'
  import { LoaderCircle } from 'lucide-vue-next'

  const props = defineProps({
    open: Boolean,
    title: {
      type: String,
      required: true
    },
    confirmLabel: {
      type: String,
      default: '确认'
    },
    busyLabel: {
      type: String,
      default: '处理中...'
    },
    cancelLabel: {
      type: String,
      default: '取消'
    },
    busy: Boolean
  })

  const emit = defineEmits(['cancel', 'confirm'])

  const onKeydown = (event) => {
    if (event.key === 'Escape' && props.open && !props.busy) emit('cancel')
  }

  watch(
    () => props.open,
    (open) => {
      if (open) document.addEventListener('keydown', onKeydown)
      else document.removeEventListener('keydown', onKeydown)
    },
    { immediate: true }
  )

  onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-overlay" @click="!busy && emit('cancel')">
      <div
        class="modal-content"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`confirm-dialog-${title}`"
        @click.stop
      >
        <h3 :id="`confirm-dialog-${title}`">{{ title }}</h3>
        <div class="confirm-dialog-body"><slot /></div>
        <div class="modal-actions">
          <button
            class="cancel-button"
            type="button"
            :disabled="busy"
            @click="emit('cancel')"
          >
            {{ cancelLabel }}
          </button>
          <button
            class="confirm-delete-button"
            type="button"
            :disabled="busy"
            @click="emit('confirm')"
          >
            <LoaderCircle v-if="busy" :size="16" class="spin" />
            <slot v-else name="confirm-icon"></slot>
            <span>{{ busy ? busyLabel : confirmLabel }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
  .confirm-dialog-body {
    color: var(--text-soft);
    font-size: 0.92rem;
    line-height: 1.6;
  }

  .confirm-dialog-body :deep(p) {
    margin: 0 0 20px;
  }

  .confirm-dialog-body :deep(ul) {
    margin: 0 0 20px;
  }
</style>
