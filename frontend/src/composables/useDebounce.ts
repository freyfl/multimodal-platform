import { ref, watch, type Ref } from 'vue'

export function useDebounce<T>(value: Ref<T>, delay = 300) {
  const debouncedValue = ref<T>(value.value) as Ref<T>
  let timer: ReturnType<typeof setTimeout> | null = null

  const stop = () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  watch(
    value,
    (newValue) => {
      stop()
      timer = setTimeout(() => {
        debouncedValue.value = newValue
      }, delay)
    },
    { immediate: true }
  )

  return {
    debouncedValue,
    stop
  }
}
