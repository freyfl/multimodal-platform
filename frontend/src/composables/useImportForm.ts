import { computed, reactive, ref, watch } from 'vue'
import { getAnnotationConfig } from '@/api/annotations'
import { getTagSystem } from '@/api/tags'
import { useSystemStore } from '@/stores/system'
import { validModelSelection, validTosDirectory } from '@/utils/modelCatalog'
import type { StartImportParams, TagSource } from '@/types'

export const MAX_CUSTOM_TAG_PROMPT_LENGTH = 10_000
export const MAX_CUSTOM_ANNOTATION_PROMPT_LENGTH = 8_000

export interface ImportFormState {
  tosDirectory: string
  embeddingModel: string
  embeddingDimension: number | undefined
  tagModel: string
  generateVectors: boolean
  generateTags: boolean
  tagMode: TagSource
  customTagPrompt: string
  generateAnnotations: boolean
  annotationMode: StartImportParams['annotation_mode']
  customAnnotationPrompt: string
  annotationBoxMode: StartImportParams['annotation_box_mode']
  annotationSampleIntervalSeconds: number | null
  annotationMaxFrames: number | null
}

export function useImportForm() {
  const system = useSystemStore()
  const formState = reactive<ImportFormState>({
    tosDirectory: '', embeddingModel: '', embeddingDimension: undefined,
    tagModel: '', generateVectors: true, generateTags: true,
    tagMode: 'default', customTagPrompt: '',
    generateAnnotations: true, annotationMode: 'default', customAnnotationPrompt: '',
    annotationBoxMode: '2d', annotationSampleIntervalSeconds: 1, annotationMaxFrames: 60,
  })
  const defaultTagPrompt = ref('')
  const defaultTagPromptLoading = ref(false)
  const defaultAnnotationPrompt = ref('')
  const annotationConfigLoading = ref(false)
  const annotationConfigError = ref('')
  const annotationModel = ref('')
  const estimateDurationSeconds = ref<number | null>(60)
  const annotationEstimate = computed(() => {
    const duration = estimateDurationSeconds.value
    const interval = formState.annotationSampleIntervalSeconds
    const maximum = formState.annotationMaxFrames
    if (!duration || duration <= 0 || !interval || interval < 1 || !maximum || maximum < 1) {
      return '填写视频时长可估算抽样帧数；图片按 1 帧处理。'
    }
    const targets = Math.ceil(duration / interval)
    return `该视频预计抽样 ${Math.min(targets, maximum)} 帧${targets > maximum ? '，均匀覆盖全片' : ''}；实际解码去重后可能更少，非逐帧标注。`
  })
  const customAnnotationPromptPlaceholder = computed(() => defaultAnnotationPrompt.value
    || (annotationConfigLoading.value ? '正在加载默认标注 Prompt...' : '请输入自定义标注规则'))
  const EMBEDDING_MODELS = computed(() => system.catalog?.embedding_models ?? {})
  const TAG_MODELS = computed(() => Object.entries(system.catalog?.tag_models ?? {})
    .map(([value, model]) => ({ value, label: model.name })))
  const availableDimensions = computed(() =>
    (EMBEDDING_MODELS.value[formState.embeddingModel]?.dimensions ?? [])
      .map(value => ({ value, label: `${value}维` })))
  const customTagPromptPlaceholder = computed(() => {
    if (defaultTagPrompt.value) return defaultTagPrompt.value
    return defaultTagPromptLoading.value
      ? '正在加载默认标签 Prompt…'
      : '默认标签 Prompt 暂不可用，请填写自定义标签规则'
  })

  function resetForm() {
    const defaults = system.catalog?.defaults
    Object.assign(formState, {
      tosDirectory: '', embeddingModel: defaults?.embedding_model ?? '',
      embeddingDimension: defaults?.embedding_dimension, tagModel: defaults?.tag_model ?? '',
      generateVectors: true, generateTags: true,
      tagMode: 'default', customTagPrompt: '',
      generateAnnotations: true, annotationMode: 'default', customAnnotationPrompt: '',
      annotationBoxMode: '2d', annotationSampleIntervalSeconds: 1, annotationMaxFrames: 60,
    })
    estimateDurationSeconds.value = 60
  }
  async function loadAnnotationConfig() {
    if (annotationConfigLoading.value) return
    annotationConfigLoading.value = true
    annotationConfigError.value = ''
    try {
      const response = await getAnnotationConfig()
      const config = response.data
      if (typeof config?.default_prompt !== 'string' || !config.default_prompt.trim()
        || typeof config?.model !== 'string' || !config.model) {
        throw new Error('Invalid annotation config')
      }
      defaultAnnotationPrompt.value = config.default_prompt
      annotationModel.value = config.model
    } catch {
      defaultAnnotationPrompt.value = ''
      annotationModel.value = ''
      annotationConfigError.value = '标注配置加载失败，请重试；也可关闭生成标注后导入。'
    } finally {
      annotationConfigLoading.value = false
    }
  }
  async function loadDefaultTagPrompt() {
    defaultTagPromptLoading.value = true
    try {
      const response = await getTagSystem()
      defaultTagPrompt.value = response?.data?.default_prompt?.trim() ?? ''
    } catch {
      defaultTagPrompt.value = ''
    } finally {
      defaultTagPromptLoading.value = false
    }
  }
  watch(() => system.catalog, resetForm, { immediate: true })
  watch(() => formState.embeddingModel, model => {
    formState.embeddingDimension = EMBEDDING_MODELS.value[model]?.default_dimension
  })
  watch(() => formState.generateAnnotations, enabled => {
    if (!enabled) {
      formState.customAnnotationPrompt = ''
      formState.annotationMode = 'default'
    }
  }, { flush: 'sync' })
  watch(() => formState.annotationMode, mode => {
    if (mode === 'default') formState.customAnnotationPrompt = ''
  }, { flush: 'sync' })
  const formError = computed(() => {
    if (!system.catalogReady) return system.configError || '正在加载模型目录，暂不能提交'
    if (!validTosDirectory(formState.tosDirectory)) return '请输入 tos://bucket/ 或 tos://bucket/prefix/'
    if (!formState.generateVectors && !formState.generateTags && !formState.generateAnnotations) return '请至少选择一个处理阶段'
    if (!validModelSelection(system.catalog, formState.embeddingModel, formState.embeddingDimension, formState.tagModel)) {
      return '模型或维度与当前向量集合不兼容'
    }
    if (formState.generateTags && formState.tagMode === 'custom') {
      const prompt = formState.customTagPrompt.trim()
      if (!prompt) return '请输入自定义标签 Prompt'
      if (prompt.length > MAX_CUSTOM_TAG_PROMPT_LENGTH) {
        return `自定义标签 Prompt 最多 ${MAX_CUSTOM_TAG_PROMPT_LENGTH} 个字符`
      }
    }
    if (formState.generateAnnotations) {
      if (annotationConfigLoading.value) return '正在加载标注配置'
      if (annotationConfigError.value) return annotationConfigError.value
      if (formState.tagModel !== annotationModel.value) return '标注需使用配置中的 Seed 2.1 模型'
      if (formState.annotationMode === 'custom') {
        const length = Array.from(formState.customAnnotationPrompt.trim()).length
        if (!length) return '请输入自定义标注 Prompt'
        if (length > MAX_CUSTOM_ANNOTATION_PROMPT_LENGTH) return '自定义标注 Prompt 最多 8000 个字符'
      }
      const interval = formState.annotationSampleIntervalSeconds
      const maximum = formState.annotationMaxFrames
      if (!Number.isInteger(interval) || interval! < 1 || interval! > 60) return '标注采样间隔需为 1–60 秒的整数'
      if (!Number.isInteger(maximum) || maximum! < 1 || maximum! > 120) return '每视频最大帧数需为 1–120 的整数'
    }
    return ''
  })
  function toRequest(): StartImportParams {
    if (formError.value) throw new Error(formError.value)
    const customTagPrompt = formState.customTagPrompt.trim()
    return {
      tos_directory: formState.tosDirectory, embedding_model: formState.embeddingModel,
      embedding_dimension: formState.embeddingDimension!, tag_model: formState.tagModel,
      generate_vectors: formState.generateVectors, generate_tags: formState.generateTags,
      tag_mode: formState.tagMode,
      custom_tag_prompt: formState.generateTags && formState.tagMode === 'custom'
        ? customTagPrompt
        : null,
      generate_annotations: formState.generateAnnotations,
      annotation_mode: formState.generateAnnotations ? formState.annotationMode : 'default',
      custom_annotation_prompt: formState.generateAnnotations && formState.annotationMode === 'custom'
        ? formState.customAnnotationPrompt.trim() : null,
      annotation_box_mode: formState.generateAnnotations ? formState.annotationBoxMode : '2d+3d',
      annotation_sample_interval_seconds: formState.generateAnnotations ? formState.annotationSampleIntervalSeconds! : 1,
      annotation_max_frames: formState.generateAnnotations ? formState.annotationMaxFrames! : 60,
    }
  }
  void loadDefaultTagPrompt()
  void loadAnnotationConfig()
  return {
    system, formState, EMBEDDING_MODELS, TAG_MODELS, availableDimensions,
    defaultTagPromptLoading, customTagPromptPlaceholder,
    defaultAnnotationPrompt, annotationConfigLoading, annotationConfigError, annotationModel,
    customAnnotationPromptPlaceholder, loadAnnotationConfig, estimateDurationSeconds, annotationEstimate,
    formError, resetForm, toRequest,
  }
}
