import { onBeforeUnmount, onMounted } from 'vue'

export function useClickOutside(targetRef, callback, eventName = 'mousedown') {
  const handleEvent = (event) => {
    const target = targetRef.value
    if (target && !target.contains(event.target)) callback(event)
  }

  onMounted(() => document.addEventListener(eventName, handleEvent))
  onBeforeUnmount(() => document.removeEventListener(eventName, handleEvent))
}
