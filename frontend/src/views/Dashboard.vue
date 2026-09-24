<template>
  <div class="dashboard-page">
    <!-- Page Header -->
    <div class="dashboard-header">
      <h1 class="dashboard-title">数据概览</h1>
      <p class="dashboard-subtitle">自动驾驶多模态数据检索平台 · 实时监控</p>
    </div>

    <!-- Stats Grid -->
    <div class="stats-grid">
      <StatCard
        title="数据总量"
        :value="systemStore.stats?.media?.total ?? 0"
        color="blue"
      >
        <template #icon><DatabaseOutlined /></template>
      </StatCard>
      <StatCard
        title="图片数量"
        :value="systemStore.stats?.media?.images ?? 0"
        color="green"
      >
        <template #icon><FileImageOutlined /></template>
      </StatCard>
      <StatCard
        title="视频数量"
        :value="systemStore.stats?.media?.videos ?? 0"
        color="orange"
      >
        <template #icon><VideoCameraOutlined /></template>
      </StatCard>
      <StatCard
        title="总搜索次数"
        :value="systemStore.stats?.performance?.total_searches ?? 0"
        color="purple"
      >
        <template #icon><SearchOutlined /></template>
      </StatCard>
    </div>

    <!-- Two Column Layout -->
    <div class="dashboard-grid">
      <!-- Data Type Distribution -->
      <GlassCard title="数据类型分布">
        <div class="type-distribution">
          <div class="dist-item" v-for="item in typeDistribution" :key="item.label">
            <div class="dist-header">
              <span class="dist-label">{{ item.label }}</span>
              <span class="dist-value">{{ item.count }} 个 ({{ item.percent }}%)</span>
            </div>
            <div class="dist-bar-track">
              <div
                class="dist-bar-fill"
                :class="item.colorClass"
                :style="{ width: item.percent + '%' }"
              ></div>
            </div>
          </div>
          <div v-if="typeDistribution.length === 0" class="dist-empty">
            暂无数据
          </div>
        </div>
      </GlassCard>

      <!-- Recent Tasks -->
      <GlassCard class="tasks-card">
        <template #header>
          <span class="glass-card-title">最近任务</span>
          <router-link to="/tasks" class="view-all-link">
            查看全部
            <RightOutlined class="link-icon" />
          </router-link>
        </template>
        <div class="recent-task-list" v-if="recentTasks.length > 0">
          <div class="recent-task-item" v-for="task in recentTasks" :key="task.task_id">
            <div class="task-info">
              <div class="task-main-name">{{ task.task_id }}</div>
              <div class="task-meta">{{ task.tos_directory }} · {{ task.total_files ?? 0 }} 文件</div>
            </div>
            <StatusBadge :status="task.status" />
          </div>
        </div>
        <EmptyState
          v-else
          title="暂无导入任务"
          description="前往数据导入页面创建新任务"
          :icon="InboxOutlined"
        />
      </GlassCard>
    </div>

    <!-- Storage Bucket Overview -->
    <GlassCard class="bucket-card">
      <template #header>
        <span class="glass-card-title">存储桶概览</span>
        <span class="bucket-badge" v-if="dashboardData?.bucket">TOS</span>
      </template>
      <div v-if="dashboardData?.bucket" class="bucket-info-section">
        <div class="bucket-detail-row">
          <div class="bucket-detail-item">
            <span class="bucket-detail-label">存储桶</span>
            <span class="bucket-detail-value bucket-name-mono">{{ dashboardData.bucket.bucket_name }}</span>
          </div>
          <div class="bucket-detail-item">
            <span class="bucket-detail-label">区域</span>
            <span class="bucket-detail-value">{{ dashboardData.bucket.region || '-' }}</span>
          </div>
          <div class="bucket-detail-item">
            <span class="bucket-detail-label">端点</span>
            <span class="bucket-detail-value bucket-name-mono">{{ dashboardData.bucket.endpoint }}</span>
          </div>
          <div class="bucket-detail-item">
            <span class="bucket-detail-label">存储用量</span>
            <span class="bucket-detail-value">{{ systemStore.stats?.media?.storage_used_gb ?? 0 }} GB</span>
          </div>
        </div>
      </div>
      <div v-else class="bucket-empty">
        <CloudServerOutlined class="bucket-empty-icon" />
        <span>未配置 TOS 存储桶</span>
      </div>
    </GlassCard>

    <!-- Imported Directories -->
    <GlassCard class="dirs-card">
      <template #header>
        <span class="glass-card-title">已导入目录</span>
        <router-link to="/import" class="view-all-link">
          导入数据
          <RightOutlined class="link-icon" />
        </router-link>
      </template>
      <div class="table-wrapper" v-if="importedDirs.length > 0">
        <a-table
          :dataSource="importedDirs"
          :columns="dirColumns"
          :pagination="false"
          row-key="task_id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'task_id'">
              <span class="dir-task-id">{{ record.task_id }}</span>
            </template>
            <template v-else-if="column.key === 'tos_directory'">
              <span class="dir-path" :title="record.tos_directory">
                <FolderOutlined class="dir-icon" />
                {{ record.tos_directory }}
              </span>
            </template>
            <template v-else-if="column.key === 'status'">
              <StatusBadge :status="record.status" />
            </template>
            <template v-else-if="column.key === 'files'">
              <span class="dir-files">{{ record.processed_files ?? 0 }} / {{ record.total_files ?? 0 }}</span>
            </template>
            <template v-else-if="column.key === 'created_at'">
              <span class="time-text">{{ formatTime(record.created_at) }}</span>
            </template>
          </template>
        </a-table>
      </div>
      <EmptyState
        v-else
        title="暂无导入记录"
        description="前往数据导入页面开始导入"
        :icon="FolderOpenOutlined"
      />
    </GlassCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useSystemStore } from '@/stores/system'
import { useImportStore } from '@/stores/import'
import { getDashboardInfo } from '@/api/system'
import StatCard from '@/components/common/StatCard/StatCard.vue'
import GlassCard from '@/components/common/GlassCard/GlassCard.vue'
import StatusBadge from '@/components/common/StatusBadge/StatusBadge.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import {
  RightOutlined,
  InboxOutlined,
  FolderOutlined,
  FolderOpenOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  FileImageOutlined,
  VideoCameraOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'

const systemStore = useSystemStore()
const importStore = useImportStore()
const dashboardData = ref<any>(null)

// Recent tasks - top 5
const recentTasks = computed(() => {
  return [...importStore.tasks]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5)
})

// Imported directories from dashboard API
const importedDirs = computed(() => {
  return dashboardData.value?.imported_dirs ?? []
})

// Data type distribution
const typeDistribution = computed(() => {
  const stats = systemStore.stats?.media
  if (!stats) return []
  const total = stats.total || 0
  if (total === 0) return []
  const items: { label: string; count: number; percent: number; colorClass: string }[] = []
  if (stats.images) {
    items.push({
      label: '图片',
      count: stats.images,
      percent: Math.round((stats.images / total) * 100),
      colorClass: 'bar-blue',
    })
  }
  if (stats.videos) {
    items.push({
      label: '视频',
      count: stats.videos,
      percent: Math.round((stats.videos / total) * 100),
      colorClass: 'bar-green',
    })
  }
  return items
})

const dirColumns = [
  { title: '任务ID', key: 'task_id', dataIndex: 'task_id', width: 180 },
  { title: 'TOS 目录', key: 'tos_directory', dataIndex: 'tos_directory', ellipsis: true },
  { title: '状态', key: 'status', dataIndex: 'status', width: 100 },
  { title: '文件数', key: 'files', width: 120 },
  { title: '导入时间', key: 'created_at', dataIndex: 'created_at', width: 160 },
]

function formatTime(dateStr: string): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function fetchDashboard() {
  try {
    const res = await getDashboardInfo()
    dashboardData.value = res?.data || null
  } catch (e) {
    console.error('获取概览数据失败:', e)
  }
}

onMounted(() => {
  systemStore.fetchStats()
  systemStore.checkHealth()
  importStore.fetchTasks()
  fetchDashboard()
})
</script>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dashboard-header {
  margin-bottom: 0;
}

.dashboard-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--gray-900, #0f172a);
  margin: 0 0 4px 0;
}

.dashboard-subtitle {
  font-size: 13px;
  color: var(--gray-500, #64748b);
  margin: 0;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

/* Dashboard Grid - two column */
.dashboard-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 1024px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

/* === Data Type Distribution === */
.type-distribution {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dist-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dist-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dist-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-800, #1e293b);
}

.dist-value {
  font-size: 12px;
  color: var(--gray-500, #64748b);
  font-variant-numeric: tabular-nums;
}

.dist-bar-track {
  height: 8px;
  background: var(--gray-100, #f1f5f9);
  border-radius: 4px;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.6s ease;
}

.bar-blue {
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
}

.bar-green {
  background: linear-gradient(90deg, #10b981, #34d399);
}

.bar-orange {
  background: linear-gradient(90deg, #f97316, #fb923c);
}

.dist-empty {
  text-align: center;
  padding: 30px 0;
  color: var(--gray-400, #9ca3af);
  font-size: 13px;
}

/* === Tasks Card === */
.tasks-card :deep(.glass-card-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.glass-card-title {
  font-size: var(--text-base, 14px);
  font-weight: 600;
  color: var(--color-text-bright, #0f172a);
}

.view-all-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-xs, 12px);
  color: var(--color-primary, #0064ff);
  text-decoration: none;
  font-weight: 500;
  transition: opacity 0.15s;
}
.view-all-link:hover {
  opacity: 0.8;
}
.link-icon {
  font-size: 10px;
}

/* Recent task list */
.recent-task-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.recent-task-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
}
.recent-task-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.recent-task-item:first-child {
  padding-top: 0;
}

.task-info {
  flex: 1;
  min-width: 0;
}

.task-main-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-800, #1e293b);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.task-meta {
  font-size: 11px;
  color: var(--gray-400, #9ca3af);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* === Bucket Card === */
.bucket-card :deep(.glass-card-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.bucket-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-primary, #0064ff);
  background: rgba(0, 100, 255, 0.08);
  letter-spacing: 0.5px;
}

.bucket-info-section {
  /* nothing extra */
}

.bucket-detail-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.bucket-detail-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bucket-detail-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--gray-500, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.bucket-detail-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-800, #1e293b);
}

.bucket-name-mono {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 12px;
}

.bucket-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 0;
  color: var(--gray-400, #9ca3af);
  font-size: 13px;
}

.bucket-empty-icon {
  font-size: 18px;
}

/* === Imported Dirs Table === */
.dirs-card :deep(.glass-card-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.table-wrapper {
  overflow-x: auto;
  margin: -20px;
}

.table-wrapper :deep(.ant-table) {
  font-size: 13px;
}

.table-wrapper :deep(.ant-table-thead > tr > th) {
  background: var(--gray-50, #f8fafc);
  font-size: var(--text-xs, 11px);
  font-weight: 600;
  color: var(--gray-500, #64748b);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
}

.table-wrapper :deep(.ant-table-tbody > tr > td) {
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
  padding: 10px 16px;
}

.table-wrapper :deep(.ant-table-tbody > tr:hover > td) {
  background: var(--gray-50, #f8fafc);
}

.dir-task-id {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 12px;
  color: var(--gray-600, #475569);
}

.dir-path {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-800, #1e293b);
}

.dir-icon {
  color: var(--gray-400, #9ca3af);
  font-size: 13px;
}

.dir-files {
  font-size: 12px;
  font-weight: 500;
  color: var(--gray-600, #475569);
  font-variant-numeric: tabular-nums;
}

.time-text {
  font-size: var(--text-xs, 12px);
  color: var(--gray-500, #64748b);
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .bucket-detail-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
