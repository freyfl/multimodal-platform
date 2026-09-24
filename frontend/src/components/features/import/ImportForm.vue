<template>
  <a-form :model="formState" layout="vertical" class="import-form">
    <ModelCatalogStatus />
    <a-form-item label="TOS目录地址" class="form-item">
      <a-input-group compact class="input-group">
        <a-input
          v-model:value="formState.tosDirectory"
          placeholder="tos://your-bucket/path/to/media/"
          size="large"
          class="tos-input"
        />
        <a-button @click="handleValidate" :loading="validating" class="validate-btn">
          验证
        </a-button>
      </a-input-group>
      <div class="form-tip">
        <InfoCircleOutlined />
        支持格式: MP4, AVI, MOV, JPG, PNG, WEBP
      </div>
    </a-form-item>

    <a-form-item label="处理选项" class="form-item">
      <div class="options-grid">
        <div
          class="option-card"
          :class="{ active: formState.generateVectors }"
          @click="formState.generateVectors = !formState.generateVectors"
        >
          <div class="option-icon">
            <ThunderboltOutlined />
          </div>
          <div class="option-content">
            <div class="option-title">生成向量</div>
            <div class="option-desc">{{ formState.embeddingModel }}</div>
          </div>
          <div class="option-check" v-if="formState.generateVectors">
            <CheckOutlined />
          </div>
        </div>

        <div
          class="option-card"
          :class="{ active: formState.generateTags }"
          @click="formState.generateTags = !formState.generateTags"
        >
          <div class="option-icon">
            <TagsOutlined />
          </div>
          <div class="option-content">
            <div class="option-title">生成标签</div>
            <div class="option-desc">{{ formState.tagModel }}</div>
          </div>
          <div class="option-check" v-if="formState.generateTags">
            <CheckOutlined />
          </div>
        </div>
        <button
          type="button"
          class="option-card"
          :class="{ active: formState.generateAnnotations }"
          :aria-pressed="formState.generateAnnotations"
          @click="formState.generateAnnotations = !formState.generateAnnotations"
        >
          <div class="option-icon"><ScanOutlined /></div>
          <div class="option-content">
            <div class="option-title">生成标注</div>
            <div class="option-desc">Seed 2.1</div>
            <div class="form-tip">默认开启，将增加模型调用费用和处理时间</div>
          </div>
          <div class="option-check" v-if="formState.generateAnnotations"><CheckOutlined /></div>
        </button>
      </div>
    </a-form-item>

    <!-- 模型配置 -->
    <a-form-item label="模型配置" class="form-item" v-if="formState.generateVectors || formState.generateTags">
      <div class="model-config">
        <div class="config-row" v-if="formState.generateVectors">
          <label class="config-label">向量模型</label>
          <a-select v-model:value="formState.embeddingModel" class="config-select">
            <a-select-option v-for="(_, key) in EMBEDDING_MODELS" :key="key" :value="key">
              {{ key }}
            </a-select-option>
          </a-select>
        </div>

        <div class="config-row" v-if="formState.generateVectors">
          <label class="config-label">向量维度</label>
          <a-select v-model:value="formState.embeddingDimension" class="config-select">
            <a-select-option v-for="dim in availableDimensions" :key="dim.value" :value="dim.value">
              {{ dim.label }}
            </a-select-option>
          </a-select>
        </div>

        <div class="config-row" v-if="formState.generateTags">
          <label class="config-label">标签模型</label>
          <a-select v-model:value="formState.tagModel" class="config-select">
            <a-select-option v-for="model in TAG_MODELS" :key="model.value" :value="model.value">
              {{ model.label }}
            </a-select-option>
          </a-select>
        </div>
      </div>
    </a-form-item>

    <a-form-item v-if="formState.generateTags" label="标签生成规则" class="form-item">
      <div class="tag-rule-config">
        <a-radio-group v-model:value="formState.tagMode" button-style="solid">
          <a-radio-button value="default">默认标签</a-radio-button>
          <a-radio-button value="custom">自定义标签</a-radio-button>
        </a-radio-group>
        <div v-if="formState.tagMode === 'custom'" class="custom-prompt">
          <a-textarea
            v-model:value="formState.customTagPrompt"
            :placeholder="customTagPromptPlaceholder"
            :maxlength="MAX_CUSTOM_TAG_PROMPT_LENGTH"
            :auto-size="{ minRows: 8, maxRows: 16 }"
            show-count
          />
          <div class="form-tip">
            请描述标签分类、标签值及适用规则。默认 Prompt 仅作占位参考，不会自动提交。
          </div>
        </div>
      </div>
    </a-form-item>

    <a-form-item v-if="formState.generateAnnotations" label="标注生成规则（独立于标签）" class="form-item">
      <div class="tag-rule-config">
        <div class="form-tip">模型：Seed 2.1 <span v-if="annotationModel">（{{ annotationModel }}）</span></div>
        <a-alert v-if="annotationConfigError" type="warning" :message="annotationConfigError" show-icon />
        <a-button v-if="annotationConfigError" :loading="annotationConfigLoading" @click="loadAnnotationConfig">重试加载标注配置</a-button>
        <a-radio-group v-model:value="formState.annotationMode" button-style="solid">
          <a-radio-button value="default">默认标注</a-radio-button>
          <a-radio-button value="custom">自定义标注</a-radio-button>
        </a-radio-group>
        <a-textarea
          v-if="formState.annotationMode === 'default'"
          :value="defaultAnnotationPrompt"
          :placeholder="annotationConfigLoading ? '正在加载默认标注 Prompt...' : '默认标注 Prompt 暂不可用'"
          :auto-size="{ minRows: 6, maxRows: 12 }"
          aria-label="默认标注 Prompt（只读）"
          readonly
          class="readonly-prompt"
        />
        <div v-else class="custom-prompt">
          <a-textarea
            v-model:value="formState.customAnnotationPrompt"
            :placeholder="customAnnotationPromptPlaceholder"
            :auto-size="{ minRows: 6, maxRows: 12 }"
            aria-label="自定义标注 Prompt"
          />
          <div class="form-tip">去除首尾空白后限 1–8000 字符；默认 Prompt 仅为占位参考，不会提交。系统几何与 JSON 合同不可覆盖。</div>
        </div>
        <a-form-item label="框类型">
          <a-radio-group v-model:value="formState.annotationBoxMode">
            <a-radio value="2d">2D 框</a-radio>
            <a-radio value="2d+3d">2D + 3D 投影框（实验）</a-radio>
          </a-radio-group>
          <div class="form-tip">当前 Seed 2.1 的 3D 实测请求可能超时；3D 投影不代表真实尺寸或距离，无法可靠估计时仅保留 2D 框。</div>
        </a-form-item>
        <div class="sampling-grid">
          <a-form-item label="目标采样间隔（秒）">
            <a-input-number v-model:value="formState.annotationSampleIntervalSeconds" :min="1" :max="60" :step="1" />
          </a-form-item>
          <a-form-item label="每视频最大帧数">
            <a-input-number v-model:value="formState.annotationMaxFrames" :min="1" :max="120" :step="1" />
          </a-form-item>
          <a-form-item label="估算视频时长（秒，不提交）">
            <a-input-number v-model:value="estimateDurationSeconds" :min="1" :max="1800" />
          </a-form-item>
        </div>
        <div class="form-tip">{{ annotationEstimate }}</div>
        <a-alert
          type="info"
          message="每张图片 / 抽样帧将增加模型调用。超出帧上限时均匀采样覆盖全片；帧数仅为估算，耗时和费用随内容、重试与服务负载变化，不保证完成时间。"
          show-icon
        />
      </div>
    </a-form-item>

    <div class="form-actions">
      <a-button
        type="primary"
        size="large"
        @click="handleSubmit"
        :loading="loading"
        :disabled="!!formError"
        class="import-btn"
      >
        <CloudUploadOutlined />
        开始导入
      </a-button>
      <a-button size="large" @click="handleReset" class="reset-btn">
        重置
      </a-button>
    </div>
    <div v-if="formError" class="form-tip">{{ formError }}</div>
  </a-form>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import {
  CloudUploadOutlined,
  ThunderboltOutlined,
  TagsOutlined,
  ScanOutlined,
  CheckOutlined,
  InfoCircleOutlined
} from '@ant-design/icons-vue'

import ModelCatalogStatus from '@/components/common/ModelCatalogStatus.vue'
import {
  MAX_CUSTOM_TAG_PROMPT_LENGTH,
  useImportForm
} from '@/composables/useImportForm'
import { validTosDirectory } from '@/utils/modelCatalog'
import type { StartImportParams } from '@/types'

withDefaults(defineProps<{
  loading?: boolean
}>(), {
  loading: false
})

const emit = defineEmits<{
  submit: [params: StartImportParams]
  validate: [directory: string]
  reset: []
}>()

const validating = ref<boolean>(false)
const {
  formState, EMBEDDING_MODELS, TAG_MODELS, availableDimensions,
  customTagPromptPlaceholder, formError, resetForm, toRequest,
  defaultAnnotationPrompt, annotationConfigLoading, annotationConfigError, annotationModel,
  customAnnotationPromptPlaceholder, loadAnnotationConfig, estimateDurationSeconds, annotationEstimate,
} = useImportForm()

const handleValidate = async () => {
  if (!validTosDirectory(formState.tosDirectory)) {
    message.warning('请输入 tos://bucket/ 或 tos://bucket/prefix/')
    return
  }
  validating.value = true
  try {
    emit('validate', formState.tosDirectory)
    message.success('目录格式验证通过，连接与权限请在设置中测试')
  } catch (e) {
    message.error('目录验证失败')
  } finally {
    validating.value = false
  }
}

const handleSubmit = () => {
  if (formError.value) {
    message.warning(formError.value)
    return
  }
  emit('submit', toRequest())
}

const handleReset = () => {
  resetForm()
  emit('reset')
}
</script>

<style scoped>
.import-form {
  margin-top: 0;
}

.form-item {
  margin-bottom: var(--spacing-lg, 24px);
}

.form-item :deep(.ant-form-item-label > label) {
  color: var(--gray-700, #334155);
  font-size: var(--text-sm, 12px);
  font-weight: 600;
}

.input-group {
  display: flex;
  align-items: stretch;
}

.tos-input {
  flex: 1;
  border-radius: var(--radius-sm, 6px) 0 0 var(--radius-sm, 6px) !important;
  height: 40px !important;
}

.tos-input :deep(.ant-input) {
  height: 38px !important;
  font-family: var(--font-mono);
  font-size: var(--text-caption, 13px);
  color: var(--gray-800, #1e293b);
  background: var(--white, #ffffff);
  border-color: var(--color-border, #e2e8f0);
}

.tos-input :deep(.ant-input:focus) {
  border-color: var(--color-primary, #0064ff);
  box-shadow: 0 0 0 3px rgba(0, 100, 255, 0.08);
}

.validate-btn {
  border-radius: 0 var(--radius-sm, 6px) var(--radius-sm, 6px) 0 !important;
  height: 40px !important;
  margin-left: -1px;
  color: var(--gray-700, #334155);
  border-color: var(--color-border, #e2e8f0);
}

.validate-btn:hover {
  color: var(--color-primary, #0064ff);
  border-color: var(--color-primary, #0064ff);
}

.form-tip {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--gray-500, #64748b);
  font-size: var(--text-sm, 12px);
}

.options-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.option-card {
  text-align: left;
  font: inherit;
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  background: var(--gray-50, #f8fafc);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
  cursor: pointer;
  transition: all 0.2s ease;
  overflow: hidden;
}

.option-card:hover {
  border-color: var(--color-border-hover, #cbd5e1);
  box-shadow: var(--shadow-sm);
}

.option-card.active {
  background: var(--color-primary-bg, #e8f0ff);
  border-color: var(--color-primary, #0064ff);
  box-shadow: 0 0 0 3px rgba(0, 100, 255, 0.08);
}

.option-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-bg, #e8f0ff);
  border-radius: var(--radius-md, 10px);
  color: var(--color-primary, #0064ff);
  font-size: 18px;
}

.option-content {
  flex: 1;
}

.option-title {
  color: var(--gray-900, #0f172a);
  font-size: var(--text-base, 14px);
  font-weight: 600;
}

.option-desc {
  color: var(--gray-500, #64748b);
  font-family: var(--font-mono);
  font-size: var(--text-sm, 12px);
  margin-top: 2px;
}

.option-check {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary, #0064ff);
  border-radius: 50%;
  color: #ffffff;
  font-size: 12px;
}

.model-config {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: var(--gray-50, #f8fafc);
  border: 1px solid var(--color-border, #e2e8f0);
  border-radius: var(--radius-lg, 12px);
}

.config-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-label {
  min-width: 70px;
  color: var(--gray-600, #475569);
  font-size: var(--text-caption, 13px);
  font-weight: 500;
}

.config-select {
  flex: 1;
}

.config-select :deep(.ant-select-selector) {
  background: var(--white, #ffffff) !important;
  border-color: var(--color-border, #e2e8f0) !important;
  border-radius: var(--radius-sm, 6px) !important;
}

.config-select :deep(.ant-select-selector:hover) {
  border-color: var(--color-primary, #0064ff) !important;
}

.config-select :deep(.ant-select-selection-item) {
  color: var(--gray-800, #1e293b) !important;
  font-family: var(--font-mono);
  font-size: var(--text-sm, 12px);
}

.config-select :deep(.ant-select-arrow) {
  color: var(--gray-400, #94a3b8) !important;
}

.tag-rule-config {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 14px;
}

.custom-prompt {
  width: 100%;
}

.readonly-prompt {
  color: var(--gray-500, #64748b);
  background: var(--gray-50, #f8fafc);
}

.sampling-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.sampling-grid :deep(.ant-form-item) {
  margin-bottom: 0;
}

.custom-prompt :deep(textarea::placeholder) {
  color: var(--gray-400, #94a3b8);
  opacity: 1;
}

.custom-prompt :deep(.ant-input-data-count) {
  color: var(--gray-400, #94a3b8);
}

.form-actions {
  display: flex;
  gap: 12px;
  margin-top: var(--spacing-lg, 24px);
}

.import-btn {
  flex: 2;
  height: 44px;
  font-size: var(--text-base, 14px);
  font-weight: 600;
  border-radius: var(--radius-sm, 6px);
  background: var(--color-primary, #0064ff);
  box-shadow: 0 1px 3px rgba(0, 100, 255, 0.3);
}

.import-btn:hover:not(:disabled) {
  background: var(--color-primary-dark, #0052d9);
  box-shadow: 0 2px 8px rgba(0, 100, 255, 0.4);
}

.reset-btn {
  flex: 1;
  height: 44px;
  border-radius: var(--radius-sm, 6px);
  color: var(--gray-700, #334155);
  border-color: var(--color-border, #e2e8f0);
}

.reset-btn:hover {
  color: var(--color-primary, #0064ff);
  border-color: var(--color-primary, #0064ff);
}
</style>
