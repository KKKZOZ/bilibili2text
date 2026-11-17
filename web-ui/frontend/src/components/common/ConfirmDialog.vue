<script setup>
  import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
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
  const titleId = useId()
  const dialog = ref(null)
  const cancelButton = ref(null)
  let previouslyFocused = null
  let previousBodyOverflow = ''
  let active = false

  const focusableElements = () =>
    dialog.value
      ? [
          ...dialog.value.querySelectorAll(
            'button:not(:disabled), a[href], input:not(:disabled), [tabindex]:not([tabindex="-1"])'
          )
        ]
      : []

  const onKeydown = (event) => {
    if (!props.open) return
    if (event.key === 'Escape') {
      if (!props.busy) emit('cancel')
      return
    }
    if (event.key !== 'Tab') return
    const items = focusableElements()
    if (items.length === 0) {
      event.preventDefault()
      dialog.value?.focus()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const current = document.activeElement
    if (!dialog.value.contains(current)) {
      event.preventDefault()
      first.focus()
    } else if (event.shiftKey && current === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && current === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const activate = () => {
    if (active) return
    active = true
    previouslyFocused = document.activeElement
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onKeydown)
    // Focus the safe action first so Enter never confirms by accident.
    void nextTick(() => (cancelButton.value || dialog.value)?.focus())
  }

  const deactivate = () => {
    if (!active) return
    active = false
    document.removeEventListener('keydown', onKeydown)
    document.body.style.overflow = previousBodyOverflow
    if (
      previouslyFocused instanceof HTMLElement &&
      previouslyFocused.isConnected
    ) {
      previouslyFocused.focus()
    }
    previouslyFocused = null
  }

  watch(
    () => props.open,
    (open) => (open ? activate() : deactivate()),
    { immediate: true }
  )

  onBeforeUnmount(deactivate)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-overlay" @click="!busy && emit('cancel')">
      <div
        ref="dialog"
        class="modal-content"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        @click.stop
      >
        <h3 :id="titleId">{{ title }}</h3>
        <div class="confirm-dialog-body"><slot /></div>
        <div class="modal-actions">
          <button
            ref="cancelButton"
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
  .modal-content:focus {
    outline: none;
  }

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

  .confirm-dialog-body :deep(.inline-notice) {
    margin: -8px 0 16px;
  }
</style>
