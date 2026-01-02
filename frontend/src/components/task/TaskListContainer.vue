<template>
  <div class="task-list" :class="`task-type-${selectedTaskType}`">
    <!-- 篩選列 -->
    <TaskFilterBar
      :all-tags="allTags"
      v-model:selected-tags="selectedFilterTags"
      v-model:is-editing="isEditingFilterTags"
      v-model:custom-tag-order="customTagOrder"
      :tasks="tasks"
      @refresh="emit('refresh')"
      @tag-renamed="handleTagRenamed"
      @tag-color-changed="handleTagColorChanged"
      @tags-reordered="handleTagsReordered"
    />

    <!-- 列表標題 -->
    <div class="list-header">
      <div class="header-actions">
        <button
          class="btn btn-secondary btn-batch-edit"
          :class="{ active: isBatchEditMode }"
          @click="toggleBatchEditMode"
          :title="isBatchEditMode ? $t('taskList.exitBatchEdit') : $t('taskList.batchEdit')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 11l3 3L22 4"></path>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
          </svg>
          {{ isBatchEditMode ? $t('taskList.exitBatchEdit') : $t('taskList.batchEdit') }}
        </button>
        <button class="btn btn-secondary btn-icon" @click="emit('refresh')" title="Refresh">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- 批次編輯工具列 -->
    <BatchEditToolbar
      v-if="isBatchEditMode"
      v-model:selectedTaskIds="selectedTaskIds"
      :tasks="sortedTasks"
      :all-tags="allTags"
      @select-all="handleSelectAll"
      @deselect-all="handleDeselectAll"
      @batch-delete="handleBatchDelete"
      @batch-tags-add="handleBatchTagsAdd"
      @batch-tags-remove="handleBatchTagsRemove"
    />

    <!-- 任務類型篩選區 - 資料夾頁籤樣式 -->
    <div class="task-type-tabs">
      <button
        class="tab-btn tab-all"
        :class="{ active: selectedTaskType === 'all' }"
        @click="selectedTaskType = 'all'"
      >
        <span>全部</span>
      </button>
      <button
        class="tab-btn tab-paragraph"
        :class="{ active: selectedTaskType === 'paragraph' }"
        @click="selectedTaskType = 'paragraph'"
      >
        <span>段落</span>
      </button>
      <button
        class="tab-btn tab-subtitle"
        :class="{ active: selectedTaskType === 'subtitle' }"
        @click="selectedTaskType = 'subtitle'"
      >
        <span>字幕</span>
      </button>
    </div>

    <!-- 任務網格 -->
    <TaskGrid
      :tasks="sortedTasks"
      :is-batch-mode="isBatchEditMode"
      :selected-task-ids="selectedTaskIds"
      :all-tasks="tasks"
      :all-tags="allTags"
      @view="(taskId) => emit('view', taskId)"
      @download="(task) => emit('download', task)"
      @delete="handleDeleteTask"
      @cancel="(taskId) => emit('cancel', taskId)"
      @toggle-selection="handleToggleSelection"
      @toggle-keep-audio="handleToggleKeepAudio"
      @tags-updated="handleTaskTagsUpdated"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'
import { useTaskTags } from '../../composables/task/useTaskTags'
import TaskFilterBar from './TaskFilterBar.vue'
import BatchEditToolbar from './BatchEditToolbar.vue'
import TaskGrid from './TaskGrid.vue'

const { t: $t } = useI18n()
const { getAllTags, fetchTagColors, fetchTagOrder } = useTaskTags($t)

// Props
const props = defineProps({
  tasks: {
    type: Array,
    required: true
  }
})

// Emits
const emit = defineEmits(['download', 'refresh', 'delete', 'cancel', 'view'])

// State
const selectedFilterTags = ref([])
const selectedTaskType = ref('all') // 任務類型篩選：'all', 'paragraph', 'subtitle'
const isEditingFilterTags = ref(false)
const customTagOrder = ref([])
const isBatchEditMode = ref(false)
const selectedTaskIds = ref(new Set())

// Computed
const allTags = getAllTags(computed(() => props.tasks))

const sortedTasks = computed(() => {
  let filtered = [...props.tasks]

  // 任務類型篩選
  if (selectedTaskType.value !== 'all') {
    filtered = filtered.filter(task => task.task_type === selectedTaskType.value)
  }

  // 標籤篩選（OR 邏輯）
  if (selectedFilterTags.value.length > 0) {
    filtered = filtered.filter(task => {
      if (!task.tags || task.tags.length === 0) return false
      return task.tags.some(tag => selectedFilterTags.value.includes(tag))
    })
  }

  // 依狀態排序
  return filtered.sort((a, b) => {
    const statusOrder = { processing: 0, pending: 1, completed: 2, failed: 3 }
    return statusOrder[a.status] - statusOrder[b.status]
  })
})

// Methods - Batch Mode
function toggleBatchEditMode() {
  isBatchEditMode.value = !isBatchEditMode.value
  if (!isBatchEditMode.value) {
    selectedTaskIds.value.clear()
    selectedTaskIds.value = new Set()
  }
}

function handleToggleSelection(taskId) {
  if (selectedTaskIds.value.has(taskId)) {
    selectedTaskIds.value.delete(taskId)
  } else {
    selectedTaskIds.value.add(taskId)
  }
  selectedTaskIds.value = new Set(selectedTaskIds.value)
}

function handleSelectAll() {
  selectedTaskIds.value = new Set(sortedTasks.value.map(t => t.task_id))
}

function handleDeselectAll() {
  selectedTaskIds.value.clear()
  selectedTaskIds.value = new Set()
}

// Methods - Batch Operations
async function handleBatchDelete() {
  if (selectedTaskIds.value.size === 0) {
    alert($t('taskList.errorSelectTasksFirst'))
    return
  }

  if (!confirm($t('taskList.batchDeleteConfirm', { count: selectedTaskIds.value.size }))) {
    return
  }

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/delete', { task_ids: taskIds })
    selectedTaskIds.value.clear()
    selectedTaskIds.value = new Set()
    emit('refresh')
  } catch (error) {
    console.error($t('taskList.errorBatchDelete') + ':', error)
    alert($t('taskList.errorBatchDeleteFull', { message: error.response?.data?.detail || error.message }))
  }
}

async function handleBatchTagsAdd(tags) {
  if (selectedTaskIds.value.size === 0) return

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/tags/add', {
      task_ids: taskIds,
      tags: tags
    })
    emit('refresh')
  } catch (error) {
    console.error($t('taskList.errorBatchAddTags') + ':', error)
    alert($t('taskList.errorBatchAddTagsFull', { message: error.response?.data?.detail || error.message }))
  }
}

async function handleBatchTagsRemove(tags) {
  if (selectedTaskIds.value.size === 0) return

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/tags/remove', {
      task_ids: taskIds,
      tags: tags
    })
    emit('refresh')
  } catch (error) {
    console.error($t('taskList.errorBatchRemoveTags') + ':', error)
    alert($t('taskList.errorBatchRemoveTagsFull', { message: error.response?.data?.detail || error.message }))
  }
}

// Methods - Task Operations
function handleDeleteTask(taskId) {
  emit('delete', taskId)
}

async function handleToggleKeepAudio(task) {
  const oldValue = task.keep_audio
  const newValue = !oldValue

  // 樂觀更新
  task.keep_audio = newValue

  try {
    await api.put(`/tasks/${task.task_id}/keep-audio`, {
      keep_audio: newValue
    })
    emit('refresh')
  } catch (error) {
    // 回滾
    task.keep_audio = oldValue
    console.error('Error toggling keep audio:', error)
    alert($t('taskList.errorToggleKeepAudio'))
  }
}

async function handleTaskTagsUpdated({ taskId, tags }) {
  try {
    await api.put(`/tasks/${taskId}/tags`, { tags })
    emit('refresh')
  } catch (error) {
    console.error($t('taskList.errorUpdateTags') + ':', error)
    alert($t('taskList.errorUpdateTagsFull', { message: error.response?.data?.detail || error.message }))
  }
}

// Methods - Tag Events
function handleTagRenamed() {
  // 標籤重命名後刷新
  emit('refresh')
}

function handleTagColorChanged() {
  // 顏色變更後無需刷新，因為 composable 已更新
}

function handleTagsReordered() {
  // 標籤順序變更後無需額外操作
}

// Lifecycle
onMounted(() => {
  fetchTagColors()
  fetchTagOrder()
})
</script>

<style scoped>
.task-list {
  --color-primary-rgb: 221, 132, 72;
  --color-teal-rgb: 119, 150, 154;
  --color-text-dark-rgb: 45, 45, 45;
  --color-success-rgb: 16, 185, 129;
  --color-danger-rgb: 239, 68, 68;
  --color-primary: rgb(var(--color-primary-rgb));
  --electric-primary: #dd8448;
  --electric-card-bg: linear-gradient(135deg, #f5f5f5 0%, #ffffff 100%);
  --electric-card-shadow-hover: 0 8px 24px rgba(0, 0, 0, 0.12);
  --neu-bg: #e6e6e6;
  --neu-shadow-btn: 6px 6px 12px rgba(0, 0, 0, 0.1), -6px -6px 12px rgba(255, 255, 255, 0.8);
  --neu-shadow-btn-hover: 8px 8px 16px rgba(0, 0, 0, 0.12), -8px -8px 16px rgba(255, 255, 255, 0.9);
  --neu-shadow-btn-active: inset 4px 4px 8px rgba(0, 0, 0, 0.1), inset -4px -4px 8px rgba(255, 255, 255, 0.8);
  --neu-shadow-inset: inset 4px 4px 8px rgba(0, 0, 0, 0.08), inset -4px -4px 8px rgba(255, 255, 255, 0.6);
  --nav-recent-bg: #77969A;
}

/* 根據任務類型設置任務列表容器背景色 */
.task-list.task-type-all :deep(.tasks) {
  background-color: var(--upload-bg);;
  padding: 10px;
  border-radius: 0 8px 8px 8px;
  position: relative;
  z-index: 5;
}

.task-list.task-type-paragraph :deep(.tasks) {
  background-color: #808F7C;
  padding: 10px;
  border-radius: 0 8px 8px 8px;
  position: relative;
  z-index: 5;
}

.task-list.task-type-subtitle :deep(.tasks) {
  background-color: #77969A;
  padding: 10px;
  border-radius: 0 8px 8px 8px;
  position: relative;
  z-index: 5;
}

/* 任務類型篩選區 - 資料夾頁籤樣式 */
.task-type-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: -15px;
  padding-left: 0px;
  position: relative;
  z-index: 1;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 40px 18px 40px;
  border: none;
  border-radius: 8px 8px 0 0;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  font-size: 14px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.8);
  position: relative;
  z-index: 1;
}

/* 全部頁籤顏色 */
.tab-btn.tab-all {
  background: var(--upload-bg);
}

/* 段落頁籤顏色 */
.tab-btn.tab-paragraph {
  background: #808F7C;
  color: rgba(255, 255, 255, 0.95);
}

/* 字幕頁籤顏色 */
.tab-btn.tab-subtitle {
  background: #77969A;
  color: rgba(255, 255, 255, 0.95);
}

.tab-btn:hover:not(.active) {
  transform: translateY(-2px);
  filter: brightness(1.05);
}

.tab-btn.active {
  font-weight: 600;
  transform: translateY(-4px);
  z-index: 10 !important;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}

.btn-secondary {
  background: rgba(var(--color-teal-rgb), 0.1);
  color: #77969a;
  border: 1px solid rgba(var(--color-teal-rgb), 0.3);
}

.btn-secondary:hover {
  background: rgba(var(--color-teal-rgb), 0.2);
}

.btn-secondary.active {
  background: rgba(var(--color-teal-rgb), 0.25);
  border-color: rgba(var(--color-teal-rgb), 0.5);
}

.btn-icon {
  padding: 8px 12px;
}

.btn-batch-edit {
  gap: 8px;
}
</style>
