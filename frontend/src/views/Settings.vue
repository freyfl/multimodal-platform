<template>
  <div class="settings-page">
    <PageHeader eyebrow="多模态工作台 / 系统" title="系统设置" subtitle="管理用户账号、角色权限和系统配置" />

    <a-tabs v-model:activeKey="activeTab" class="settings-tabs">
      <!-- Tab 1: 用户管理（仅管理员） -->
      <a-tab-pane v-if="isAdmin" key="users" tab="用户管理">
        <!-- 统计卡片 -->
        <div class="stats-grid">
          <StatCard index="01" title="总用户数" :value="userStats.total"><template #icon><TeamOutlined /></template></StatCard>
          <StatCard index="02" title="管理员" :value="userStats.admins"><template #icon><SafetyCertificateOutlined /></template></StatCard>
          <StatCard index="03" title="活跃用户" :value="userStats.active"><template #icon><ThunderboltOutlined /></template></StatCard>
        </div>

        <!-- 用户列表 -->
        <GlassCard class="table-card" padding="0">
          <template #header>
            <span class="card-title">用户列表</span>
            <div class="header-actions">
              <a-input
                v-model:value="searchKeyword"
                placeholder="搜索用户名或邮箱..."
                allow-clear
                class="search-input"
              >
                <template #prefix><SearchOutlined /></template>
              </a-input>
              <a-button type="primary" @click="showCreateModal">
                <template #icon><PlusOutlined /></template>
                新增用户
              </a-button>
            </div>
          </template>

          <div class="table-responsive">
            <a-table
              :columns="columns"
              :data-source="filteredUsers"
              :loading="loading"
              :pagination="pagination"
              row-key="id"
              class="user-table"
              @change="handleTableChange"
            >
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'username'">
                  <div class="user-cell">
                    <span class="user-avatar">{{ record.username.charAt(0).toUpperCase() }}</span>
                    <span class="user-name">{{ record.username }}</span>
                  </div>
                </template>

                <template v-else-if="column.key === 'email'">
                  <span class="email-text">{{ record.email || '—' }}</span>
                </template>

                <template v-else-if="column.key === 'role'">
                  <div class="role-cell">
                    <TagBadge
                      :label="record.role === 'admin' ? '管理员' : '普通用户'"
                      :color="record.role === 'admin' ? 'blue' : 'gray'"
                    />
                    <TagBadge v-if="record.is_demo === 1" label="Demo" color="purple" />
                  </div>
                </template>

                <template v-else-if="column.key === 'is_active'">
                  <StatusBadge
                    :status="record.is_active === 1 ? 'running' : 'failed'"
                    :text="record.is_active === 1 ? '已启用' : '已禁用'"
                  />
                </template>

                <template v-else-if="column.key === 'created_at'">
                  <span class="time-text">{{ formatTime(record.created_at) }}</span>
                </template>

                <template v-else-if="column.key === 'actions'">
                  <div class="action-cell">
                    <a-tooltip title="配置凭证">
                      <a-button type="text" size="small" @click="showUserSettings(record)">
                        <template #icon><KeyOutlined /></template>
                      </a-button>
                    </a-tooltip>
                    <a-tooltip title="编辑">
                      <a-button type="text" size="small" @click="showEditModal(record)">
                        <template #icon><EditOutlined /></template>
                      </a-button>
                    </a-tooltip>
                    <a-tooltip title="登录日志">
                      <a-button type="text" size="small" @click="showLoginLogs(record)">
                        <template #icon><FileTextOutlined /></template>
                      </a-button>
                    </a-tooltip>
                    <a-tooltip :title="record.is_active === 1 ? '禁用' : '启用'">
                      <a-popconfirm
                        :title="`确认${record.is_active === 1 ? '禁用' : '启用'}该用户？`"
                        ok-text="确认"
                        cancel-text="取消"
                        @confirm="toggleUserActive(record)"
                      >
                        <a-button
                          type="text"
                          size="small"
                          :class="{ 'btn-danger': record.is_active === 1 }"
                        >
                          <template #icon>
                            <StopOutlined v-if="record.is_active === 1" />
                            <CheckCircleOutlined v-else />
                          </template>
                        </a-button>
                      </a-popconfirm>
                    </a-tooltip>
                  </div>
                </template>
              </template>

              <template #emptyText>
                <EmptyState
                  title="暂无用户"
                  description="点击「新增用户」创建第一个用户账号"
                  :icon="TeamOutlined"
                />
              </template>
            </a-table>
          </div>
        </GlassCard>
      </a-tab-pane>

      <!-- Tab 2: 系统配置（所有用户可见） -->
      <a-tab-pane key="system" tab="系统配置">
        <div class="system-settings-wrap">
          <ModelCatalogStatus />
          <a-alert v-if="settingsError" type="error" :message="settingsError" show-icon />
          <a-alert
            v-if="settingsTargetUser"
            type="info"
            show-icon
            closable
            :message="`正在配置用户：${settingsTargetUser.username}`"
            @close="showMySettings"
          />
          <a-alert
            v-if="settingsReadOnly"
            type="warning"
            show-icon
            message="演示账号配置由管理员维护，当前仅可查看。"
          />
          <div v-if="!isCustomSettings" class="default-config-banner">
            <div class="banner-icon">
              <InfoCircleOutlined />
            </div>
            <div class="banner-content">
              <span class="banner-title">当前尚未配置独立凭证</span>
              <span class="banner-desc">业务操作不会使用部署级凭证，请填写该用户自己的 TOS 与方舟配置。</span>
            </div>
          </div>

          <!-- TOS 对象存储配置 -->
          <GlassCard class="config-card">
            <template #header>
              <div class="config-card-header">
                <div class="config-card-title-group">
                  <span class="config-card-icon config-card-icon--tos"><CloudServerOutlined /></span>
                  <div>
                    <div class="config-card-title">TOS 对象存储配置</div>
                    <div class="config-card-desc">火山引擎 TOS 存储桶访问凭证与连接信息</div>
                  </div>
                </div>
                <a-button :loading="testTosLoading" :disabled="!settingsReady || settingsReadOnly" size="small" @click="handleTestTos">
                  <template #icon><ApiOutlined /></template>
                  测试连接
                </a-button>
              </div>
            </template>
            <a-form layout="vertical" class="config-form" :disabled="settingsReadOnly">
              <a-row :gutter="16">
                <a-col :span="12">
                  <a-form-item label="AccessKey ID">
                    <a-input-password v-model:value="sysForm.tos_access_key_id" :placeholder="savedSettings?.tos_access_key_id_masked ? '已配置，留空保留' : '请输入 TOS AccessKey ID'" />
                  </a-form-item>
                </a-col>
                <a-col :span="12">
                  <a-form-item label="AccessKey Secret">
                    <a-input-password v-model:value="sysForm.tos_access_key_secret" :placeholder="tosSecretPlaceholder" />
                  </a-form-item>
                </a-col>
              </a-row>
              <a-row :gutter="16">
                <a-col :span="12">
                  <a-form-item label="Bucket 名称">
                    <a-input v-model:value="sysForm.tos_bucket_name" placeholder="请输入 Bucket 名称" />
                  </a-form-item>
                </a-col>
                <a-col :span="12">
                  <a-form-item label="Endpoint">
                    <a-input v-model:value="sysForm.tos_endpoint" placeholder="填写 TOS 控制台提供的 Endpoint" />
                  </a-form-item>
                </a-col>
              </a-row>
              <a-row :gutter="16">
                <a-col :span="12">
                  <a-form-item label="Region">
                    <a-input v-model:value="sysForm.tos_region" placeholder="填写存储桶所在地域" />
                  </a-form-item>
                </a-col>
                <a-col :span="12">
                  <a-form-item label="自定义域名">
                    <a-input v-model:value="sysForm.tos_custom_domain" placeholder="可选，已配置签名访问的自定义域名" />
                  </a-form-item>
                </a-col>
              </a-row>
              <a-form-item label="Security Token（临时凭证，可选）">
                <a-input-password v-model:value="sysForm.tos_security_token"
                  :placeholder="savedSettings?.tos_security_token_masked ? '已配置，留空保留' : '使用临时凭证时填写'" />
              </a-form-item>
              <a-alert v-if="tosTestResult" :type="tosTestResult.success ? 'success' : 'error'"
                :message="tosTestResult.success ? 'TOS 连接成功' : formatServiceError(tosTestResult.error)" />
            </a-form>
          </GlassCard>

          <!-- 方舟 API 配置 -->
          <GlassCard class="config-card">
            <template #header>
              <div class="config-card-header">
                <div class="config-card-title-group">
                  <span class="config-card-icon config-card-icon--api"><KeyOutlined /></span>
                  <div>
                    <div class="config-card-title">方舟 API 配置</div>
                    <div class="config-card-desc">火山引擎方舟大模型平台 Ark API 密钥</div>
                  </div>
                </div>
                <a-button :loading="testArkLoading" :disabled="!canSave || settingsReadOnly" size="small" @click="handleTestArk">
                  <template #icon><ApiOutlined /></template>
                  测试两类模型
                </a-button>
              </div>
            </template>
            <a-form layout="vertical" class="config-form" :disabled="settingsReadOnly">
              <a-form-item label="Ark API Key">
                <a-input-password v-model:value="sysForm.ark_api_key" :placeholder="apiKeyPlaceholder" />
              </a-form-item>
              <template v-if="arkTestResult">
                <a-alert v-for="kind in (['embedding', 'tag'] as const)" :key="kind"
                  :type="arkTestResult[kind]?.success ? 'success' : 'error'"
                  :message="`${kind === 'embedding' ? '向量模型' : '标签模型'}：${arkTestResult[kind]?.success ? '可用' : formatServiceError(arkTestResult[kind]?.error)}`" />
              </template>
            </a-form>
          </GlassCard>

          <!-- 模型配置 -->
          <GlassCard class="config-card">
            <template #header>
              <div class="config-card-header">
                <div class="config-card-title-group">
                  <span class="config-card-icon config-card-icon--model"><SettingOutlined /></span>
                  <div>
                    <div class="config-card-title">模型配置</div>
                    <div class="config-card-desc">向量化模型选择与维度参数设置</div>
                  </div>
                </div>
              </div>
            </template>
            <a-form layout="vertical" class="config-form" :disabled="settingsReadOnly">
              <a-row :gutter="16">
                <a-col :span="12">
                  <a-form-item label="向量化模型">
                    <a-select v-model:value="sysForm.embedding_model" placeholder="选择向量化模型" @change="onModelChange">
                      <a-select-option v-for="(model, id) in system.catalog?.embedding_models" :key="id" :value="id">{{ model.name }}</a-select-option>
                    </a-select>
                  </a-form-item>
                </a-col>
                <a-col :span="12">
                  <a-form-item label="向量维度">
                    <a-select v-model:value="sysForm.embedding_dimension" placeholder="向量维度">
                      <a-select-option v-for="dimension in dimensions" :key="dimension" :value="dimension">{{ dimension }} 维</a-select-option>
                    </a-select>
                  </a-form-item>
                </a-col>
              </a-row>
              <a-form-item label="标签模型">
                <a-select v-model:value="sysForm.tag_model" placeholder="选择标签模型">
                  <a-select-option v-for="(model, id) in system.catalog?.tag_models" :key="id" :value="id">{{ model.name }}</a-select-option>
                </a-select>
              </a-form-item>
              <a-alert v-if="system.catalogReady && !modelValid" type="error" message="模型或维度与当前集合不兼容，请重新选择" />
            </a-form>
          </GlassCard>

          <!-- 底部操作栏 -->
          <div class="config-actions">
            <a-button type="primary" :loading="saveLoading" :disabled="!canSave || settingsReadOnly" @click="handleSave">
              保存配置
            </a-button>
            <a-button @click="handleReset">
              恢复已保存配置
            </a-button>
            <div class="config-actions-spacer"></div>
            <a-popconfirm
              title="确认删除该用户的独立配置？删除后相关业务能力将不可用。"
              ok-text="确认删除"
              cancel-text="取消"
              @confirm="handleDelete"
            >
              <a-button danger :disabled="!isCustomSettings || settingsReadOnly">
                删除自定义配置
              </a-button>
            </a-popconfirm>
          </div>
        </div>
      </a-tab-pane>
    </a-tabs>

    <!-- 新增用户对话框 -->
    <a-modal
      v-model:open="createModalVisible"
      title="新增用户"
      :confirm-loading="createLoading"
      @ok="handleCreate"
      @cancel="resetCreateForm"
      ok-text="创建"
      cancel-text="取消"
    >
      <a-form
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        layout="vertical"
        class="modal-form"
      >
        <a-form-item label="用户名" name="username">
          <a-input v-model:value="createForm.username" placeholder="请输入用户名（至少3个字符）" />
        </a-form-item>
        <a-form-item label="密码" name="password">
          <a-input-password v-model:value="createForm.password" placeholder="请输入密码（至少6个字符）" />
        </a-form-item>
        <a-form-item label="邮箱" name="email">
          <a-input v-model:value="createForm.email" placeholder="请输入邮箱（可选）" />
        </a-form-item>
        <a-form-item label="角色" name="role">
          <a-select v-model:value="createForm.role" placeholder="选择角色">
            <a-select-option value="user">普通用户</a-select-option>
            <a-select-option value="admin">管理员</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="演示账号">
          <a-switch
            :checked="createForm.is_demo === 1"
            :disabled="createForm.role === 'admin'"
            @change="(val: boolean) => createForm.is_demo = val ? 1 : 0"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 编辑用户对话框 -->
    <a-modal
      v-model:open="editModalVisible"
      title="编辑用户"
      :confirm-loading="editLoading"
      @ok="handleEdit"
      @cancel="resetEditForm"
      ok-text="保存"
      cancel-text="取消"
    >
      <a-form
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        layout="vertical"
        class="modal-form"
      >
        <a-form-item label="用户名">
          <a-input :value="editingUser?.username" disabled />
        </a-form-item>
        <a-form-item label="邮箱" name="email">
          <a-input v-model:value="editForm.email" placeholder="请输入邮箱" />
        </a-form-item>
        <a-form-item label="角色" name="role">
          <a-select v-model:value="editForm.role">
            <a-select-option value="user">普通用户</a-select-option>
            <a-select-option value="admin">管理员</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="演示账号">
          <a-switch
            :checked="editForm.is_demo === 1"
            :disabled="editForm.role === 'admin'"
            @change="(val: boolean) => editForm.is_demo = val ? 1 : 0"
          />
        </a-form-item>
        <a-form-item label="状态" name="is_active">
          <a-switch
            :checked="editForm.is_active === 1"
            @change="(val: boolean) => editForm.is_active = val ? 1 : 0"
            checked-children="启用"
            un-checked-children="禁用"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 登录日志抽屉 -->
    <a-drawer
      v-model:open="logsDrawerVisible"
      :title="`登录日志 — ${logsUser?.username ?? ''}`"
      width="560"
      placement="right"
    >
      <a-table
        :columns="logColumns"
        :data-source="loginLogs"
        :loading="logsLoading"
        :pagination="logsPagination"
        row-key="id"
        size="small"
        class="logs-table"
        @change="handleLogsTableChange"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <StatusBadge
              :status="record.status === 'success' ? 'completed' : 'failed'"
              :text="record.status === 'success' ? '成功' : '失败'"
            />
          </template>
          <template v-else-if="column.key === 'user_agent'">
            <span class="ua-text" :title="record.user_agent">{{ shortenUA(record.user_agent) }}</span>
          </template>
          <template v-else-if="column.key === 'created_at'">
            <span class="time-text">{{ formatTime(record.created_at) }}</span>
          </template>
        </template>

        <template #emptyText>
          <EmptyState title="暂无登录日志" description="该用户还没有登录记录" :icon="FileTextOutlined" />
        </template>
      </a-table>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import type { FormInstance } from 'ant-design-vue'
import {
  SearchOutlined,
  PlusOutlined,
  EditOutlined,
  FileTextOutlined,
  StopOutlined,
  CheckCircleOutlined,
  TeamOutlined,
  ApiOutlined,
  CloudServerOutlined,
  KeyOutlined,
  SettingOutlined,
  InfoCircleOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import GlassCard from '@/components/common/GlassCard/GlassCard.vue'
import PageHeader from '@/components/common/PageHeader/PageHeader.vue'
import StatCard from '@/components/common/StatCard/StatCard.vue'
import StatusBadge from '@/components/common/StatusBadge/StatusBadge.vue'
import TagBadge from '@/components/common/TagBadge/TagBadge.vue'
import EmptyState from '@/components/common/EmptyState/EmptyState.vue'
import { usersApi } from '@/api/users'
import type { UserResponse, LoginLog } from '@/api/users'
import { settingsApi } from '@/api/settings'
import type { UserSettingsResponse, UserSettingsUpdate, ArkTestResult, ConnectionTestResult } from '@/api/settings'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'
import { validModelSelection } from '@/utils/modelCatalog'
import { formatServiceError, settingsPayload } from '@/utils/settings'
import ModelCatalogStatus from '@/components/common/ModelCatalogStatus.vue'

// ── Auth ──
const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin ?? false)

// ── Tabs ──
const activeTab = ref(isAdmin.value ? 'users' : 'system')

// =====================================================
// ===           用户管理 Tab（仅管理员）              ===
// =====================================================

// ── 用户列表 ──
const loading = ref(false)
const users = ref<UserResponse[]>([])
const totalUsers = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const searchKeyword = ref('')

const userStats = computed(() => {
  const all = users.value
  return {
    total: totalUsers.value,
    admins: all.filter(u => u.role === 'admin').length,
    active: all.filter(u => u.is_active === 1).length,
  }
})

const filteredUsers = computed(() => {
  if (!searchKeyword.value.trim()) return users.value
  const kw = searchKeyword.value.toLowerCase()
  return users.value.filter(
    u => u.username.toLowerCase().includes(kw) || (u.email && u.email.toLowerCase().includes(kw))
  )
})

const pagination = computed(() => ({
  current: currentPage.value,
  pageSize: pageSize.value,
  total: totalUsers.value,
  showSizeChanger: true,
  showTotal: (total: number) => `共 ${total} 条`,
}))

const columns = [
  { title: '用户名', key: 'username', width: 180 },
  { title: '邮箱', key: 'email', dataIndex: 'email', ellipsis: true },
  { title: '角色', key: 'role', width: 120 },
  { title: '状态', key: 'is_active', width: 110 },
  { title: '创建时间', key: 'created_at', width: 160 },
  { title: '操作', key: 'actions', width: 176, fixed: 'right' as const },
]

async function fetchUsers() {
  loading.value = true
  try {
    const res = await usersApi.getUsers(currentPage.value, pageSize.value)
    users.value = res.items
    totalUsers.value = res.total
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

function handleTableChange(pag: any) {
  currentPage.value = pag.current
  pageSize.value = pag.pageSize
  fetchUsers()
}

// ── 新增用户 ──
const createModalVisible = ref(false)
const createLoading = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({
  username: '',
  password: '',
  email: '',
  role: 'user',
  is_demo: 0,
})

const createRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }, { min: 3, message: '用户名至少3个字符', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { min: 6, message: '密码至少6个字符', trigger: 'blur' }],
  email: [{ type: 'email' as const, message: '请输入有效的邮箱地址', trigger: 'blur' }],
}

function showCreateModal() {
  createModalVisible.value = true
}

function resetCreateForm() {
  createForm.username = ''
  createForm.password = ''
  createForm.email = ''
  createForm.role = 'user'
  createForm.is_demo = 0
  createFormRef.value?.resetFields()
}

async function handleCreate() {
  try {
    await createFormRef.value?.validate()
  } catch {
    return
  }
  createLoading.value = true
  try {
    const data: any = {
      username: createForm.username,
      password: createForm.password,
      role: createForm.role,
      is_demo: createForm.role === 'admin' ? 0 : createForm.is_demo,
    }
    if (createForm.email) data.email = createForm.email
    await usersApi.createUser(data)
    message.success('用户创建成功')
    createModalVisible.value = false
    resetCreateForm()
    fetchUsers()
  } catch {
    // handled by interceptor
  } finally {
    createLoading.value = false
  }
}

// ── 编辑用户 ──
const editModalVisible = ref(false)
const editLoading = ref(false)
const editFormRef = ref<FormInstance>()
const editingUser = ref<UserResponse | null>(null)
const editForm = reactive({
  email: '',
  role: 'user',
  is_demo: 0,
  is_active: 1,
})

const editRules = {
  email: [{ type: 'email' as const, message: '请输入有效的邮箱地址', trigger: 'blur' }],
}

function showEditModal(user: UserResponse) {
  editingUser.value = user
  editForm.email = user.email || ''
  editForm.role = user.role
  editForm.is_demo = user.is_demo
  editForm.is_active = user.is_active
  editModalVisible.value = true
}

function resetEditForm() {
  editingUser.value = null
  editForm.email = ''
  editForm.role = 'user'
  editForm.is_demo = 0
  editForm.is_active = 1
  editFormRef.value?.resetFields()
}

async function handleEdit() {
  try {
    await editFormRef.value?.validate()
  } catch {
    return
  }
  if (!editingUser.value) return
  editLoading.value = true
  try {
    await usersApi.updateUser(editingUser.value.id, {
      email: editForm.email || undefined,
      role: editForm.role,
      is_demo: editForm.role === 'admin' ? 0 : editForm.is_demo,
      is_active: editForm.is_active,
    })
    message.success('用户更新成功')
    editModalVisible.value = false
    resetEditForm()
    fetchUsers()
  } catch {
    // handled by interceptor
  } finally {
    editLoading.value = false
  }
}

// ── 启用/禁用 ──
async function toggleUserActive(user: UserResponse) {
  try {
    await usersApi.updateUser(user.id, { is_active: user.is_active === 1 ? 0 : 1 })
    message.success(user.is_active === 1 ? '用户已禁用' : '用户已启用')
    fetchUsers()
  } catch {
    // handled by interceptor
  }
}

// ── 登录日志 ──
const logsDrawerVisible = ref(false)
const logsLoading = ref(false)
const logsUser = ref<UserResponse | null>(null)
const loginLogs = ref<LoginLog[]>([])
const logsTotal = ref(0)
const logsPage = ref(1)
const logsPageSize = ref(20)

const logColumns = [
  { title: 'IP 地址', dataIndex: 'ip_address', key: 'ip_address', width: 140 },
  { title: 'User-Agent', key: 'user_agent', dataIndex: 'user_agent', ellipsis: true },
  { title: '状态', key: 'status', width: 90 },
  { title: '时间', key: 'created_at', width: 160 },
]

const logsPagination = computed(() => ({
  current: logsPage.value,
  pageSize: logsPageSize.value,
  total: logsTotal.value,
  showTotal: (total: number) => `共 ${total} 条`,
  size: 'small' as const,
}))

async function showLoginLogs(user: UserResponse) {
  logsUser.value = user
  logsPage.value = 1
  logsDrawerVisible.value = true
  await fetchLoginLogs()
}

async function fetchLoginLogs() {
  if (!logsUser.value) return
  logsLoading.value = true
  try {
    const res = await usersApi.getUserLoginLogs(logsUser.value.id, logsPage.value, logsPageSize.value)
    loginLogs.value = res.items
    logsTotal.value = res.total
  } catch {
    // handled by interceptor
  } finally {
    logsLoading.value = false
  }
}

function handleLogsTableChange(pag: any) {
  logsPage.value = pag.current
  logsPageSize.value = pag.pageSize
  fetchLoginLogs()
}

// =====================================================
// ===           系统配置 Tab（所有用户）              ===
// =====================================================

const system = useSystemStore()
const settingsTargetUser = ref<UserResponse | null>(null)
const settingsReadOnly = computed(
  () => !settingsTargetUser.value && authStore.user?.is_demo === 1,
)
const dimensions = computed(() => system.catalog?.embedding_models[sysForm.embedding_model]?.dimensions ?? [])
const modelValid = computed(() => validModelSelection(system.catalog, sysForm.embedding_model, sysForm.embedding_dimension, sysForm.tag_model))
const settingsError = ref('')
const settingsReady = computed(() => !!savedSettings.value && !settingsLoading.value && !settingsError.value)
const canSave = computed(() => settingsReady.value && system.catalogReady && modelValid.value)
const tosTestResult = ref<ConnectionTestResult | null>(null)
const arkTestResult = ref<ArkTestResult | null>(null)

const isCustomSettings = ref(false)
const savedSettings = ref<UserSettingsResponse | null>(null)
const settingsLoading = ref(false)
const saveLoading = ref(false)
const testTosLoading = ref(false)
const testArkLoading = ref(false)

const sysForm = reactive<{
  tos_access_key_id: string
  tos_access_key_secret: string
  tos_security_token: string
  tos_bucket_name: string
  tos_endpoint: string
  tos_region: string
  tos_custom_domain: string
  ark_api_key: string
  embedding_model: string
  tag_model: string
  embedding_dimension: number | undefined
}>({
  tos_access_key_id: '',
  tos_access_key_secret: '',
  tos_security_token: '',
  tos_bucket_name: '',
  tos_endpoint: '',
  tos_region: '',
  tos_custom_domain: '',
  ark_api_key: '',
  embedding_model: '',
  tag_model: '',
  embedding_dimension: undefined,
})

const tosSecretPlaceholder = computed(() =>
  savedSettings.value?.tos_access_key_secret_masked ? '已配置，留空保留' : '请输入 TOS AccessKey Secret'
)
const apiKeyPlaceholder = computed(() =>
  savedSettings.value?.ark_api_key_masked ? '已配置，留空保留' : '请输入方舟 API Key'
)

function populateForm(data: UserSettingsResponse) {
  sysForm.tos_access_key_id = ''
  sysForm.tos_access_key_secret = '' // 密码字段不回填
  sysForm.tos_security_token = ''
  sysForm.tos_bucket_name = data.tos_bucket_name || ''
  sysForm.tos_endpoint = data.tos_endpoint || ''
  sysForm.tos_region = data.tos_region || ''
  sysForm.tos_custom_domain = data.tos_custom_domain || ''
  sysForm.ark_api_key = '' // 密码字段不回填
  sysForm.embedding_model = data.embedding_model ?? system.catalog?.defaults.embedding_model ?? ''
  sysForm.embedding_dimension = data.embedding_dimension ?? system.catalog?.defaults.embedding_dimension
  sysForm.tag_model = data.tag_model ?? system.catalog?.defaults.tag_model ?? ''
}

watch(() => system.catalog, () => {
  if (!sysForm.embedding_model) sysForm.embedding_model = system.catalog?.defaults.embedding_model ?? ''
  if (sysForm.embedding_dimension === undefined) sysForm.embedding_dimension = system.catalog?.defaults.embedding_dimension
  if (!sysForm.tag_model) sysForm.tag_model = system.catalog?.defaults.tag_model ?? ''
})
watch(sysForm, () => { tosTestResult.value = null; arkTestResult.value = null })

async function fetchSettings() {
  settingsLoading.value = true
  settingsError.value = ''
  try {
    const data = settingsTargetUser.value
      ? await settingsApi.getUserSettings(settingsTargetUser.value.id)
      : await settingsApi.getMySettings()
    savedSettings.value = data
    // id 为空字符串表示尚未保存独立配置。
    isCustomSettings.value = !!data.id
    populateForm(data)
  } catch {
    settingsError.value = '配置加载失败，暂不能保存或测试，请恢复已保存配置重试'
  } finally {
    settingsLoading.value = false
  }
}

async function showUserSettings(user: UserResponse) {
  settingsTargetUser.value = user
  activeTab.value = 'system'
  await fetchSettings()
}

async function showMySettings() {
  settingsTargetUser.value = null
  await fetchSettings()
}

function onModelChange(model: string) {
  sysForm.embedding_dimension = system.catalog?.embedding_models[model]?.default_dimension
}

async function handleTestTos() {
  if (!settingsReady.value) return
  testTosLoading.value = true
  try {
    const payload = settingsPayload(sysForm)
    const tosPayload = Object.fromEntries(Object.entries(payload).filter(([key]) => key.startsWith('tos_'))) as UserSettingsUpdate
    tosTestResult.value = settingsTargetUser.value
      ? await settingsApi.testUserTos(settingsTargetUser.value.id, tosPayload)
      : await settingsApi.testTos(tosPayload)
  } catch {
    tosTestResult.value = { success: false, message: 'TOS 连接测试请求失败' }
    message.error('TOS 连接测试请求失败')
  } finally {
    testTosLoading.value = false
  }
}

async function handleTestArk() {
  if (!canSave.value) return
  testArkLoading.value = true
  try {
    const payload = settingsPayload(sysForm)
    arkTestResult.value = settingsTargetUser.value
      ? await settingsApi.testUserArk(settingsTargetUser.value.id, payload)
      : await settingsApi.testArk(payload)
  } catch {
    arkTestResult.value = {
      success: false,
      embedding: { success: false, message: '测试请求失败，未确认可用' },
      tag: { success: false, message: '测试请求失败，未确认可用' },
    }
    message.error('API Key 测试请求失败')
  } finally {
    testArkLoading.value = false
  }
}

async function handleSave() {
  if (!canSave.value) return
  saveLoading.value = true
  try {
    const payload = settingsPayload(sysForm)
    if (settingsTargetUser.value) {
      await settingsApi.updateUserSettings(settingsTargetUser.value.id, payload)
    } else {
      await settingsApi.updateMySettings(payload)
    }
    message.success('配置已保存')
    await fetchSettings()
  } catch {
    // handled by interceptor
  } finally {
    saveLoading.value = false
  }
}

async function handleReset() {
  await fetchSettings()
  message.info('已重置为当前保存的配置')
}

async function handleDelete() {
  try {
    if (settingsTargetUser.value) {
      await settingsApi.deleteUserSettings(settingsTargetUser.value.id)
    } else {
      await settingsApi.deleteMySettings()
    }
    message.success('独立配置已删除')
    await fetchSettings()
  } catch {
    // handled by interceptor
  }
}

// ── Helpers ──
function formatTime(dateStr: string | null): string {
  if (!dateStr) return '—'
  try {
    const d = new Date(dateStr)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return dateStr
  }
}

function shortenUA(ua: string): string {
  if (!ua) return '—'
  if (ua.length <= 40) return ua
  return ua.substring(0, 40) + '…'
}

// ── Init ──
onMounted(() => {
  if (isAdmin.value) {
    fetchUsers()
  }
  fetchSettings()
})
</script>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  animation: fadeInUp 0.4s ease both;
}

@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Page Header ── */
/* ── Tabs ── */
.settings-tabs :deep(.ant-tabs-nav) {
  margin-bottom: 20px;
}

/* ── Stats ── */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}

/* ── Table Card Header ── */
.table-card :deep(.glass-card-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.card-title {
  font-size: var(--text-base, 14px);
  font-weight: 600;
  color: var(--color-text-bright, #0f172a);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-input {
  width: 220px;
}

/* ── Table ── */
.table-responsive {
  overflow-x: auto;
}

.user-table :deep(.ant-table) {
  background: transparent;
}

.user-table :deep(.ant-table-thead > tr > th) {
  background: var(--gray-50, #f8fafc);
  border-bottom: 1px solid var(--color-border, #e2e8f0);
  color: var(--gray-500, #64748b);
  font-size: var(--text-xs, 11px);
  font-weight: 600;
  letter-spacing: 0.5px;
  padding: 10px 16px;
}

.user-table :deep(.ant-table-tbody > tr > td) {
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
  padding: 12px 16px;
  font-size: 13px;
  color: var(--gray-700, #334155);
  transition: background 0.15s ease;
}

.user-table :deep(.ant-table-tbody > tr:hover > td) {
  background: var(--gray-50, #f8fafc) !important;
}

/* ── User Cell ── */
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--color-primary, #0064ff), var(--color-primary-light, #4080ff));
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  flex-shrink: 0;
}

.user-name {
  font-weight: 600;
  color: var(--gray-800, #1e293b);
}

.email-text {
  color: var(--gray-500, #64748b);
  font-size: 13px;
}

.role-cell {
  display: flex;
  align-items: center;
  gap: 4px;
}

.time-text {
  font-size: var(--text-xs, 12px);
  color: var(--gray-400, #94a3b8);
}

/* ── Action Cell ── */
.action-cell {
  display: flex;
  align-items: center;
  gap: 2px;
}

.btn-danger {
  color: var(--color-error, #ef4444) !important;
}

/* ── Modal Form ── */
.modal-form {
  padding-top: 8px;
}

/* ── Logs Table ── */
.logs-table :deep(.ant-table-thead > tr > th) {
  background: var(--gray-50, #f8fafc);
  font-size: var(--text-xs, 11px);
  font-weight: 600;
  color: var(--gray-500, #64748b);
  letter-spacing: 0.5px;
}

.logs-table :deep(.ant-table-tbody > tr > td) {
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-subtle, #f1f5f9);
}

.ua-text {
  font-size: 12px;
  color: var(--gray-500, #64748b);
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}

/* ── System Settings ── */
.system-settings-wrap {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ── Default Config Banner ── */
.default-config-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 16px;
  background: var(--color-primary-bg, #e8f0ff);
  border: 1px solid rgba(0, 100, 255, 0.12);
  border-radius: var(--radius-md, 10px);
}

.banner-icon {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius, 8px);
  background: rgba(0, 100, 255, 0.1);
  color: var(--color-primary, #0064ff);
  font-size: 16px;
}

.banner-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 4px;
}

.banner-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary-dark, #0052d9);
}

.banner-desc {
  font-size: 12px;
  color: var(--gray-500, #64748b);
  line-height: 1.5;
}

/* ── Config Card Header ── */
.config-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.config-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-card-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius, 8px);
  font-size: 17px;
}

.config-card-icon--tos {
  background: rgba(0, 100, 255, 0.08);
  color: var(--color-primary, #0064ff);
}

.config-card-icon--api {
  background: rgba(245, 158, 11, 0.1);
  color: #d97706;
}

.config-card-icon--model {
  background: rgba(139, 92, 246, 0.1);
  color: var(--color-purple, #8b5cf6);
}

.config-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-bright, #0f172a);
  line-height: 1.4;
}

.config-card-desc {
  font-size: 12px;
  color: var(--gray-400, #94a3b8);
  line-height: 1.4;
}

.config-card {
  /* Card spacing handled by gap on parent */
}

.config-form {
  /* vertical layout form */
}

.config-form :deep(.ant-form-item) {
  margin-bottom: 12px;
}

.config-form :deep(.ant-form-item:last-of-type) {
  margin-bottom: 0;
}

.config-form :deep(.ant-form-item-label) {
  padding-bottom: 4px;
}

.config-form :deep(.ant-form-item-label > label) {
  font-size: 12px;
  color: var(--gray-500, #64748b);
  font-weight: 500;
}

.config-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 0 4px;
  border-top: 1px solid var(--color-border-subtle, #f1f5f9);
}

.config-actions-spacer {
  flex: 1;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
  .header-actions {
    flex-wrap: wrap;
    width: 100%;
  }
  .search-input {
    width: 100%;
  }

  .config-actions {
    flex-wrap: wrap;
  }
  .config-form :deep(.ant-col) {
    flex: 0 0 100%;
    max-width: 100%;
  }
}

@media (min-width: 769px) and (max-width: 1024px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
