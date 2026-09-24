import { ref, onUnmounted } from 'vue'

interface UseTaskPollingOptions {
  interval?: number
  shouldPoll: () => boolean
  onPoll: () => Promise<void>
}

export function useTaskPolling(options: UseTaskPollingOptions) {
  const { interval = 3000, shouldPoll, onPoll } = options
  const isPolling = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  let idleCount = 0

  const startPolling = () => {
    if (timer) return
    isPolling.value = true
    idleCount = 0
    timer = setInterval(async () => {
      if (shouldPoll()) {
        idleCount = 0
        await onPoll()
      } else {
        idleCount++
        // 连续 3 次无需轮询则自动停止
        if (idleCount >= 3) {
          stopPolling()
        }
      }
    }, interval)
  }

  const stopPolling = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    isPolling.value = false
  }

  const pollOnce = async () => {
    await onPoll()
  }

  onUnmounted(() => {
    stopPolling()
  })

  return {
    isPolling,
    startPolling,
    stopPolling,
    pollOnce
  }
}
