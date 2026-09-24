<template>
  <a-layout-footer class="app-footer">
    <div class="footer-inner">
      <div class="footer-left">
        <div class="stat-chip">
          <DatabaseOutlined class="stat-icon" />
          <span class="stat-label">索引</span>
          <span class="stat-value">{{ totalMedia.toLocaleString() }}</span>
        </div>
        <div class="stat-chip">
          <ThunderboltOutlined class="stat-icon accent" />
          <span class="stat-label">向量</span>
          <span class="stat-value">{{ vectorCount.toLocaleString() }}</span>
        </div>
        <div class="status-chip">
          <span class="dot"></span>
          <span>{{ systemStore.isHealthy ? '运行正常' : '连接异常' }}</span>
        </div>
      </div>
      <div class="footer-right">
        <span class="brand">MULTIMODAL PLATFORM</span>
        <span class="ver">v2.0.0</span>
      </div>
    </div>
  </a-layout-footer>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { DatabaseOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import { useSystemStore } from '@/stores/system'
import { useSystemStats } from '@/composables'

const systemStore = useSystemStore()
// 复用已有的 composable，自动轮询 30s
useSystemStats()

const totalMedia = computed(() => systemStore.stats?.media?.total || 0)
const vectorCount = computed(() => systemStore.stats?.vectors?.total || 0)

onMounted(() => {
  systemStore.checkHealth()
})
</script>

<style scoped>
.app-footer {
  padding: 0 !important;
  background: rgba(10, 15, 30, 0.7) !important;
  backdrop-filter: blur(16px);
  border-top: 1px solid rgba(59, 130, 246, 0.08);
  height: 40px !important;
  line-height: 40px !important;
}

.footer-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 40px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stat-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.stat-icon {
  color: #3b82f6;
  font-size: 12px;
}

.stat-icon.accent {
  color: #06b6d4;
}

.stat-label {
  color: #475569;
  font-weight: 400;
}

.stat-value {
  color: #94a3b8;
  font-family: 'Roboto Mono', monospace;
  font-weight: 500;
  font-size: 11px;
}

.status-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 4px;
  padding: 2px 10px;
  background: rgba(34, 197, 94, 0.06);
  border: 1px solid rgba(34, 197, 94, 0.12);
  border-radius: 10px;
  font-size: 10px;
  color: #4ade80;
  font-weight: 500;
}

.dot {
  width: 5px;
  height: 5px;
  background: #22c55e;
  border-radius: 50%;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.5);
  animation: pulse 3s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.footer-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand {
  font-family: 'Exo 2', sans-serif;
  color: #334155;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 1.5px;
}

.ver {
  font-family: 'Roboto Mono', monospace;
  background: rgba(59, 130, 246, 0.08);
  color: #475569;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
}
</style>
