<template>
  <div class="dashboard-page">
    <!-- Page Header -->
    <div class="dashboard-header">
      <div class="dashboard-intro">
        <div class="eyebrow"><span></span>多模态工作台 / 概览</div>
        <h1 class="dashboard-title">数据概览<span class="title-period">.</span></h1>
        <p class="dashboard-subtitle">从每一帧出发，让感知数据清晰可见。</p>
        <div class="overview-actions">
          <router-link to="/search/annotations" class="overview-link">探索标注数据 <ArrowRightOutlined /></router-link>
          <button class="refresh-overview" :disabled="refreshing" @click="refreshOverview">
            <ReloadOutlined :spin="refreshing" /> {{ refreshing ? '更新中' : '刷新概览' }}
          </button>
        </div>
      </div>
      <PerceptionGraphic class="overview-graphic" />
    </div>

    <a-alert v-if="systemStore.statsError || dashboardError" type="error" show-icon :message="systemStore.statsError || dashboardError" />
    <!-- Stats Grid -->
    <div class="stats-grid" :aria-busy="systemStore.isLoading">
      <StatCard
        index="01"
        title="数据总量"
        to="/search/annotations"
        :value="systemStore.stats?.media?.total ?? '—'"
      >
        <template #icon><DatabaseOutlined /></template>
      </StatCard>
      <StatCard
        index="02"
        title="图片数量"
        :value="systemStore.stats?.media?.images ?? '—'"
      >
        <template #icon><FileImageOutlined /></template>
      </StatCard>
      <StatCard
        index="03"
        title="视频数量"
        :value="systemStore.stats?.media?.videos ?? '—'"
      >
        <template #icon><VideoCameraOutlined /></template>
      </StatCard>
      <StatCard
        index="04"
        title="总搜索次数"
        :value="systemStore.stats?.performance?.total_searches ?? '—'"
      >
        <template #icon><SearchOutlined /></template>
      </StatCard>
    </div>

    <!-- Two Column Layout -->
    <div class="dashboard-grid">
      <!-- Data Type Distribution -->
      <GlassCard title="数据类型分布">
        <div class="distribution-intro">
          <span class="section-index">01 / 数据构成</span>
          <p>你的多模态数据资产</p>
        </div>
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
          <div v-if="typeDistribution.length === 0" class="dist-ghost" :class="{ loading: systemStore.isLoading }">
            <div v-for="ghost in ['图片', '视频']" :key="ghost" class="dist-item is-ghost" aria-hidden="true">
              <div class="dist-header">
                <span class="dist-label">{{ ghost }}</span>
                <span class="dist-value">— 个 (0%)</span>
              </div>
              <div class="dist-bar-track"><div class="dist-bar-fill"></div></div>
            </div>
            <p class="dist-empty">
              {{ systemStore.isLoading ? '正在读取数据…' : systemStore.statsError ? '统计暂不可用' : '导入图片或视频，开始积累数据资产' }}
            </p>
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
        <a-skeleton v-if="importStore.isLoading && !recentTasks.length" active :paragraph="{ rows: 2 }" />
        <div class="recent-task-list" v-else-if="recentTasks.length > 0">
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
        >
          <template #actions><router-link to="/import" class="empty-action-link">创建第一个导入任务 <ArrowRightOutlined /></router-link></template>
        </EmptyState>
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
        <span>{{ dashboardLoading ? '正在读取存储配置…' : dashboardError ? '存储配置暂不可用' : '未配置 TOS 存储桶' }}</span>
        <router-link v-if="!dashboardLoading && !dashboardError" to="/settings">前往配置 <ArrowRightOutlined /></router-link>
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
          :scroll="{ x: 760 }"
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
        :title="dashboardLoading ? '正在读取导入记录…' : dashboardError ? '导入记录暂不可用' : '暂无导入记录'"
        :description="dashboardLoading || dashboardError ? '' : '前往数据导入页面开始导入'"
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
import PerceptionGraphic from '@/components/common/PerceptionGraphic.vue'
import {
  ArrowRightOutlined,
  ReloadOutlined,
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
const dashboardError = ref('')
const dashboardLoading = ref(true)
const refreshing = ref(false)

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
  dashboardLoading.value = true
  dashboardError.value = ''
  try {
    const res = await getDashboardInfo()
    dashboardData.value = res?.data || null
  } catch (e) {
    dashboardError.value = '存储与目录概览读取失败，请刷新重试'
  } finally {
    dashboardLoading.value = false
  }
}

async function refreshOverview() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([systemStore.fetchStats(), systemStore.checkHealth(), importStore.fetchTasks(), fetchDashboard()])
  } finally {
    refreshing.value = false
  }
}
onMounted(refreshOverview)
</script>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 200px;
  padding: 4px 0 8px;
  gap: 32px;
}

.dashboard-title {
  font-size: var(--text-display);
  font-weight: 700;
  color: var(--gray-900);
  margin: 14px 0 12px;
  letter-spacing: -0.01em;
  line-height: 1.1;
}

.dashboard-subtitle {
  font-size: 14px;
  color: var(--gray-500);
  margin: 0;
}
.title-period { color: var(--color-accent); margin-left: 2px; }
.overview-graphic { width: min(40%, 410px); flex-shrink: 0; }
.overview-actions { display: flex; gap: 28px; align-items: center; margin-top: 26px; font-size: 13px; }
.overview-link { display: inline-flex; gap: 10px; align-items: center; font-weight: 500; }
.overview-link .anticon { transition: transform var(--duration-normal) var(--ease-out); }
.overview-link:hover .anticon { transform: translateX(4px); }
.refresh-overview {
  display: inline-flex; gap: 8px; align-items: center;
  color: var(--gray-500); padding: 6px 0;
  transition: color var(--transition-default);
}
.refresh-overview:hover { color: var(--gray-900); }
.refresh-overview .anticon { transition: transform var(--duration-slow) var(--ease-out); }
.refresh-overview:hover:not(:disabled) .anticon { transform: rotate(180deg); }
.refresh-overview:disabled { opacity: .6; cursor: wait; }
.distribution-intro { margin-bottom: 28px; }
.distribution-intro p { font-size: 21px; letter-spacing: -0.01em; margin: 10px 0 0; color: var(--color-text-bright); font-weight: 500; }
.empty-action-link { font-size: 12px; display: inline-flex; gap: 6px; align-items: center; }
.empty-action-link .anticon { transition: transform var(--duration-normal) var(--ease-out); }
.empty-action-link:hover .anticon { transform: translateX(3px); }

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  background: white;
  box-shadow: var(--shadow);
}
.stats-grid :deep(.stat-card) { border: 0; border-radius: 0; border-right: 1px solid var(--color-border); box-shadow: none; padding: 26px; }
.stats-grid :deep(.stat-card:last-child) { border-right: 0; }
.stats-grid[aria-busy="true"] :deep(.stat-value) { opacity: .35; }
/* Dashboard Grid - two column */
.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, .85fr) minmax(0, 1.15fr);
  gap: 24px;
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
  height: 6px;
  background: var(--gray-100);
  border-radius: 3px;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width .9s var(--ease-out);
}

.bar-blue {
  background: var(--ink);
}

.bar-green {
  background: var(--mint-deep);
}

.bar-orange {
  background: var(--color-warning);
}

.dist-ghost { display: flex; flex-direction: column; gap: 20px; }
.dist-item.is-ghost .dist-label { color: var(--gray-400); }
.dist-item.is-ghost .dist-value { color: var(--gray-300); }
.dist-item.is-ghost .dist-bar-track {
  background: repeating-linear-gradient(90deg, var(--gray-200) 0 6px, transparent 6px 12px);
  opacity: .9;
}
.dist-ghost.loading .dist-bar-track {
  background: linear-gradient(90deg, var(--gray-100) 25%, var(--gray-200) 50%, var(--gray-100) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}
.dist-empty {
  text-align: left;
  margin: 6px 0 0;
  color: var(--gray-500);
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
  color: var(--color-accent);
  text-decoration: none;
  font-weight: 500;
  transition: color var(--transition-default);
}
.view-all-link:hover {
  color: var(--color-accent-dark);
}
.link-icon {
  font-size: 10px;
  transition: transform var(--duration-normal) var(--ease-out);
}
.view-all-link:hover .link-icon { transform: translateX(3px); }

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
  border-bottom: 1px solid var(--color-border-subtle);
  transition: transform var(--duration-normal) var(--ease-out);
}
.recent-task-item:hover { transform: translateX(4px); }
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
  padding-right: 16px;
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
  font-size: 12px;
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
  padding: 3px 10px;
  border-radius: var(--radius-xs);
  font: 500 10px var(--font-mono);
  color: var(--mint-ink);
  background: var(--mint-soft);
  letter-spacing: 0.1em;
}

.bucket-info-section {
  /* nothing extra */
}

.bucket-detail-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
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
  letter-spacing: 0.5px;
}

.bucket-detail-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-800, #1e293b);
  overflow-wrap: anywhere;
}

.bucket-name-mono {
  font-family: var(--font-mono);
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
  margin: 0;
}

.table-wrapper :deep(.ant-table) {
  font-size: 13px;
}

.table-wrapper :deep(.ant-table-thead > tr > th) {
  background: var(--gray-50, #f8fafc);
  font-size: var(--text-xs, 11px);
  font-weight: 600;
  color: var(--gray-500, #64748b);
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
  font-family: var(--font-mono);
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
  .dashboard-header { min-height: 180px; }
  .stats-grid :deep(.stat-card:nth-child(2)) { border-right: 0; }
  .stats-grid :deep(.stat-card:nth-child(-n+2)) { border-bottom: 1px solid var(--color-border); }
}
@media (max-width: 600px) {
  .dashboard-page { gap: 20px; }
  .overview-graphic { display: none; }
  .dashboard-header { padding-bottom: 0; }
  .stats-grid :deep(.stat-card) { padding: 20px 16px; }
  .stats-grid :deep(.stat-icon-wrapper) { display: none; }
  .bucket-detail-row { grid-template-columns: 1fr; }
  .bucket-empty { flex-wrap: wrap; }
  .dashboard-grid { gap: 20px; }
}
</style>
