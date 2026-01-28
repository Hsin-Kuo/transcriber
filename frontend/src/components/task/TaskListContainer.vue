<template>
  <div class="task-list" :class="[`task-type-${selectedTaskType}`, { 'batch-edit-active': isBatchEditMode }]">
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
        <span>{{ $t('taskList.all') }}</span>
      </button>
      <button
        class="tab-btn tab-paragraph"
        :class="{ active: selectedTaskType === 'paragraph' }"
        @click="selectedTaskType = 'paragraph'"
      >
        <span>{{ $t('taskList.paragraph') }}</span>
      </button>
      <button
        class="tab-btn tab-subtitle"
        :class="{ active: selectedTaskType === 'subtitle' }"
        @click="selectedTaskType = 'subtitle'"
      >
        <span>{{ $t('taskList.subtitle') }}</span>
      </button>

      <button
        class="tab-btn tab-batch-edit"
        :class="{ active: isBatchEditMode }"
        @click="toggleBatchEditMode"
        :title="isBatchEditMode ? $t('taskList.exitBatchEdit') : $t('taskList.batchEdit')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
        </svg>
        <span>{{ isBatchEditMode ? $t('taskList.exitBatchEdit') : $t('taskList.batchEdit') }}</span>
      </button>

      <!-- 分頁控制 -->
      <div class="pagination-wrapper">
        <RulerPagination
          v-if="totalPages > 0"
          :key="`pagination-${currentPage}-${totalPages}`"
          :current-page="currentPage"
          :total-pages="totalPages"
          @update:current-page="handlePageChange"
        />
      </div>
    </div>

    <!-- 任務網格 -->
    <TaskGrid
      :tasks="sortedTasks"
      :is-batch-mode="isBatchEditMode"
      :selected-task-ids="selectedTaskIds"
      :all-tasks="tasks"
      :all-tags="allTags"
      @view="handleViewTask"
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
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'
import { useTaskTags } from '../../composables/task/useTaskTags'
import { taskService } from '../../api/services.js'
import TaskFilterBar from './TaskFilterBar.vue'
import BatchEditToolbar from './BatchEditToolbar.vue'
import TaskGrid from './TaskGrid.vue'
import RulerPagination from '../common/RulerPagination.vue'

const { t: $t } = useI18n()
const { fetchTagColors, fetchTagOrder } = useTaskTags($t)

// Props
const props = defineProps({
  tasks: {
    type: Array,
    required: true
  },
  currentPage: {
    type: Number,
    default: 1
  },
  totalPages: {
    type: Number,
    default: 0
  }
})

// Emits
const emit = defineEmits(['download', 'refresh', 'delete', 'cancel', 'view', 'page-change', 'filter-change'])

// 處理分頁變更
function handlePageChange(newPage) {
  emit('page-change', newPage)
}

// SessionStorage 鍵值
const STORAGE_KEY_FILTER_TAGS = 'taskList_filterTags'
const STORAGE_KEY_TASK_TYPE = 'taskList_taskType'
const STORAGE_KEY_PRESERVE_FLAG = 'taskList_preserveFilters'

// 從 sessionStorage 恢復篩選狀態
const restoreFilterState = () => {
  try {
    // 檢查是否應該保留篩選（這個標記會在離開任務列表頁面時設置）
    const shouldPreserve = sessionStorage.getItem(STORAGE_KEY_PRESERVE_FLAG) === 'true'

    // 清除標記
    sessionStorage.removeItem(STORAGE_KEY_PRESERVE_FLAG)

    if (shouldPreserve) {
      // 恢復篩選狀態
      const savedTags = sessionStorage.getItem(STORAGE_KEY_FILTER_TAGS)
      const savedType = sessionStorage.getItem(STORAGE_KEY_TASK_TYPE)

      if (savedTags) {
        selectedFilterTags.value = JSON.parse(savedTags)
      }
      if (savedType) {
        selectedTaskType.value = savedType
      }
    } else {
      // 不保留，清除篩選狀態
      sessionStorage.removeItem(STORAGE_KEY_FILTER_TAGS)
      sessionStorage.removeItem(STORAGE_KEY_TASK_TYPE)
    }
  } catch (error) {
    console.error('Failed to restore filter state:', error)
  }
}

// State
const selectedFilterTags = ref([])
const selectedTaskType = ref('all') // 任務類型篩選：'all', 'paragraph', 'subtitle'
const isEditingFilterTags = ref(false)
const customTagOrder = ref([])
const isBatchEditMode = ref(false)
const selectedTaskIds = ref(new Set())

// 監聽篩選狀態變化，保存到 sessionStorage
watch(selectedFilterTags, (newTags) => {
  try {
    sessionStorage.setItem(STORAGE_KEY_FILTER_TAGS, JSON.stringify(newTags))
  } catch (error) {
    console.error('Failed to save filter tags:', error)
  }
}, { deep: true })

watch(selectedTaskType, (newType) => {
  try {
    sessionStorage.setItem(STORAGE_KEY_TASK_TYPE, newType)
  } catch (error) {
    console.error('Failed to save task type:', error)
  }
})

// 監聽篩選條件變化，通知父組件
watch([selectedTaskType, selectedFilterTags], () => {
  emit('filter-change', {
    taskType: selectedTaskType.value === 'all' ? null : selectedTaskType.value,
    tags: selectedFilterTags.value
  })
}, { deep: true })

// Computed
// 從 API 獲取的所有標籤
const allTags = ref([])

const sortedTasks = computed(() => {
  // 後端已經處理了 task_type 和 tags 篩選
  // 這裡只需要對前端顯示的任務進行排序
  let filtered = [...props.tasks]

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
function handleViewTask(taskId) {
  // 設置保留標記，表示從任務列表導航到詳情頁面時應該保留篩選
  try {
    sessionStorage.setItem(STORAGE_KEY_PRESERVE_FLAG, 'true')
  } catch (error) {
    console.error('Failed to set preserve flag:', error)
  }
  emit('view', taskId)
}

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

    // 根據後端返回的錯誤代碼顯示對應的翻譯訊息
    const errorCode = error.response?.data?.detail?.error_code || error.response?.data?.error_code

    if (errorCode === 'KEEP_AUDIO_LIMIT_EXCEEDED') {
      alert($t('taskList.errorKeepAudioLimit'))
    } else if (errorCode === 'TASK_NOT_FOUND') {
      alert($t('transcriptData.taskNotFound'))
    } else {
      // 回退：顯示通用錯誤訊息
      const message = error.response?.data?.detail?.message || error.response?.data?.detail || error.message
      alert($t('taskList.errorToggleKeepAudio') + (message ? ': ' + message : ''))
    }
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
  // 重新獲取標籤列表
  fetchAllTags()
}

function handleTagColorChanged() {
  // 顏色變更後無需刷新，因為 composable 已更新
}

async function handleTagsReordered() {
  // 標籤順序變更後重新獲取標籤數據，確保順序同步
  await fetchTagColors()
  await fetchAllTags()
}

// 獲取所有標籤（使用 /tags API，已按 order 排序）
async function fetchAllTags() {
  try {
    const response = await api.get('/tags')
    // /tags 返回完整標籤對象（含 order），提取名稱並保持順序
    const tags = response.data || []
    allTags.value = tags.map(tag => tag.name)
  } catch (error) {
    console.error('Failed to fetch tags:', error)
    allTags.value = []
  }
}

// Lifecycle
onMounted(() => {
  restoreFilterState()
  fetchTagColors()
  fetchTagOrder()
  fetchAllTags()
})
</script>

<style scoped>
.task-list {
  --color-primary-rgb: 221, 132, 72;
  --color-teal-rgb: 119, 150, 154;
  /* --color-text-dark-rgb: 45, 45, 45; */
  --color-success-rgb: 16, 185, 129;
  --color-danger-rgb: 239, 68, 68;
  --color-primary: rgb(var(--color-primary-rgb));
  --electric-primary: #dd8448;
  --electric-card-bg: linear-gradient(135deg, #f5f5f5 0%, #ffffff 100%);
  --electric-card-shadow-hover: 0 8px 24px rgba(0, 0, 0, 0.12);
  --main-bg: #e6e6e6;
  --nav-recent-bg: #77969A;
}

/* FilterBar 統一與上方保持距離 */
.task-list :deep(.filter-section) {
  margin-top: 40px;
}

/* 根據任務類型設置任務列表容器背景色 */
.task-list.task-type-all :deep(.tasks) {
  /* background-color: var(--upload-bg); */
  padding: 10px;
  border-radius: 8px;
  position: relative;
  z-index: 5;
}

.task-list.task-type-paragraph :deep(.tasks) {
  /* background-color: var(--color-teal-light); */
  padding: 10px;
  border-radius: 8px;
  position: relative;
  z-index: 5;
}

.task-list.task-type-subtitle :deep(.tasks) {
  /* background-color: var(--color-teal); */
  padding: 10px;
  border-radius: 8px;
  position: relative;
  z-index: 5;
}

/* empty-state 根據任務類型設置背景色，在頁籤之上、.tasks 之下 */
.task-list.task-type-all :deep(.empty-state) {
  background-color: var(--upload-bg);
  border-radius: 8px;
  position: relative;
  z-index: 3;
}

.task-list.task-type-paragraph :deep(.empty-state) {
  background-color: var(--color-teal-light);
  border-radius: 8px;
  position: relative;
  z-index: 3;
}

.task-list.task-type-subtitle :deep(.empty-state) {
  background-color: var(--color-teal);
  border-radius: 8px;
  position: relative;
  z-index: 3;
}

/* 批次編輯模式優先 - 覆蓋任務類型的背景色 */
.task-list :deep(.tasks.batch-mode) {
  background: var(--nav-bg) !important;
  padding: 20px !important;
}

/* 批次編輯模式下的 empty-state 背景色 */
.task-list.batch-edit-active :deep(.empty-state) {
  background-color: var(--nav-bg) !important;
}

/* 任務類型篩選區 - 資料夾頁籤樣式 */
.task-type-tabs {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  margin-bottom: 0px;
  margin-top: 20px;
  padding-left: 0px;
  position: relative;
  z-index: 1;
}

/* 分頁控制容器 */
.pagination-wrapper {
  margin-left: auto;
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  padding-bottom: 0px;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  margin: 0px 20px 10px 20px;
  left: 10px;
  border: none;
  /* border-radius: 8px; */
  background: #00000000;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  font-size: 14px;
  font-weight: 500;
  color: var(--nav-text);
  position: relative;
  z-index: 1;
}

/* 全部頁籤顏色 */
/* .tab-btn.tab-all {
  background: #00000000;
} */

段落頁籤顏色
/* .tab-btn.tab-paragraph {
  background: #00000000;
  color: var(--nav-text);
} */

/* 字幕頁籤顏色 */
/* .tab-btn.tab-subtitle {
  background: #00000000;
  color: var(--nav-text);
} */

/* 批次編輯頁籤顏色 */
.tab-btn.tab-batch-edit {
  padding: 6px 10px;
  margin: 0px 20px 10px 20px;
  background: #00000000;
}

.tab-btn.tab-batch-edit.active {
  color: var(--color-nav-active-bg);
}

/* 批次編輯模式下，其他頁籤變成淺灰色 */
.task-list.batch-edit-active .tab-btn.tab-all,
.task-list.batch-edit-active .tab-btn.tab-paragraph,
.task-list.batch-edit-active .tab-btn.tab-subtitle {
  border-bottom: none;
  color: rgba(var(--color-text-dark-rgb), 0.5) !important;
  opacity: 0.7;
}

.tab-btn:hover:not(.active) {
  transform: translateY(-2px);
  filter: brightness(1.05);
}

.tab-btn.active {
  font-weight: 600;
  transform: translateY(-4px);
  z-index: 10 !important;
  border-bottom: 1px solid var(--nav-text);
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
  color: var(--color-teal);
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
