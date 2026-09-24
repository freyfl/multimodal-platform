import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SearchResult, MediaFile } from '@/types'

interface SearchHistoryItem {
  id: string
  type: 'text' | 'image' | 'tags'
  query: string
  timestamp: number
}

export const useSearchStore = defineStore('search', () => {
  const history = ref<SearchHistoryItem[]>([])
  const results = ref<SearchResult | null>(null)
  const selectedItems = ref<MediaFile[]>([])
  const isSearching = ref(false)

  const addToHistory = (item: Omit<SearchHistoryItem, 'id' | 'timestamp'>) => {
    history.value.unshift({
      ...item,
      id: Date.now().toString(),
      timestamp: Date.now()
    })
    // 保留最近 20 条记录
    if (history.value.length > 20) {
      history.value = history.value.slice(0, 20)
    }
  }

  const clearHistory = () => {
    history.value = []
  }

  const setResults = (data: SearchResult | null) => {
    results.value = data
  }

  const toggleSelection = (item: MediaFile) => {
    const index = selectedItems.value.findIndex(i => i.id === item.id)
    if (index === -1) {
      selectedItems.value.push(item)
    } else {
      selectedItems.value.splice(index, 1)
    }
  }

  const clearSelection = () => {
    selectedItems.value = []
  }

  const setSearching = (state: boolean) => {
    isSearching.value = state
  }

  return {
    history,
    results,
    selectedItems,
    isSearching,
    addToHistory,
    clearHistory,
    setResults,
    toggleSelection,
    clearSelection,
    setSearching
  }
})
