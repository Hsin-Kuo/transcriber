<template>
  <div class="task-list" :class="[`task-type-${selectedTaskType}`, { 'batch-edit-active': isBatchEditMode, 'has-pagination': totalPages > 0 }]">
    <!-- 頂部列：標籤篩選 + 名稱搜尋。
         搜尋框放這裡而不是頁籤列——頁籤列實測需要 870px 但只有 868px，
         塞進去會把頁籤擠到換行；標籤列則有大片留白。
         語意上搜尋與標籤同屬「縮小範圍」，放一起也合理。 -->
    <div class="task-list-header">
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

      <!-- 名稱搜尋（桌機；手機版搜尋入口在 MobileHeader，另案處理） -->
      <div class="task-search">
        <svg class="task-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="8"></circle>
          <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <input
          v-model="searchQuery"
          type="search"
          class="task-search-input"
          :maxlength="MAX_SEARCH_LENGTH"
          :disabled="isBatchEditMode"
          :placeholder="$t('taskList.filterBar.searchPlaceholder')"
          :aria-label="$t('taskList.filterBar.searchPlaceholder')"
          @keyup.esc="searchQuery = ''"
        />
        <button
          v-if="searchQuery"
          type="button"
          class="task-search-clear"
          :title="$t('taskList.filterBar.clearSearch')"
          :aria-label="$t('taskList.filterBar.clearSearch')"
          @click="searchQuery = ''"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    </div>


    <!-- 任務類型篩選區 - 資料夾頁籤樣式 -->
    <div class="task-type-tabs">
      <button
        class="tab-btn tab-all"
        :class="{ active: selectedTaskType === 'all' }"
        :disabled="isBatchEditMode"
        @click="selectedTaskType = 'all'"
      >
        <!-- 沿用原底部導覽「所有任務」的斜線方塊 icon（手機版才顯示，見 .tab-icon） -->
        <svg class="tab-icon" width="16" height="16" viewBox="0 0 20 20" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <line x1="0.8" y1="5.4" x2="5.4" y2="0.8" />
          <line x1="0.8" y1="10" x2="10" y2="0.8" />
          <line x1="0.8" y1="14.6" x2="14.6" y2="0.8" />
          <line x1="0.8" y1="19.2" x2="19.2" y2="0.8" />
          <line x1="5.4" y1="19.2" x2="19.2" y2="5.4" />
          <line x1="10" y1="19.2" x2="19.2" y2="10" />
          <line x1="14.6" y1="19.2" x2="19.2" y2="14.6" />
        </svg>
        <span>{{ $t('taskList.all') }}</span>
      </button>
      <button
        class="tab-btn tab-paragraph"
        :class="{ active: selectedTaskType === 'paragraph' }"
        :disabled="isBatchEditMode"
        @click="selectedTaskType = 'paragraph'"
      >
        <svg class="tab-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
        </svg>
        <span>{{ $t('taskList.paragraph') }}</span>
      </button>
      <button
        class="tab-btn tab-subtitle"
        :class="{ active: selectedTaskType === 'subtitle' }"
        :disabled="isBatchEditMode"
        @click="selectedTaskType = 'subtitle'"
      >
        <svg class="tab-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="4" width="20" height="16" rx="2"></rect>
          <line x1="6" y1="16" x2="18" y2="16"></line>
        </svg>
        <span>{{ $t('taskList.subtitle') }}</span>
      </button>
      <button
        class="tab-btn tab-has-audio"
        :class="{ active: selectedTaskType === 'has_audio' }"
        :disabled="isBatchEditMode"
        @click="selectedTaskType = 'has_audio'"
      >
        <!-- 音波：不等高垂直線，模擬真實波形起伏 -->
        <svg class="tab-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <line x1="3" y1="9" x2="3" y2="15"></line>
          <line x1="7.5" y1="5" x2="7.5" y2="19"></line>
          <line x1="12" y1="10" x2="12" y2="14"></line>
          <line x1="16.5" y1="3" x2="16.5" y2="20"></line>
          <line x1="21" y1="8" x2="21" y2="13"></line>
        </svg>
        <span>{{ $t('taskList.hasAudio') }}</span>
      </button>

      <!-- 進入批次編輯（編輯狀態下隱藏，退出改由底部工具列的 X） -->
      <button
        v-if="!isBatchEditMode"
        class="tab-btn tab-batch-edit"
        @click="toggleBatchEditMode"
        :title="$t('taskList.batchEdit')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
        </svg>
        <span>{{ $t('taskList.batchEdit') }}</span>
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
      :has-active-filters="hasActiveFilters"
      :search-query="debouncedSearchQuery"
      @clear-search="searchQuery = ''"
      @view="handleViewTask"
      @download="(task) => emit('download', task)"
      @delete="handleDeleteTask"
      @cancel="(taskId) => emit('cancel', taskId)"
      @toggle-selection="handleToggleSelection"
      @long-press="handleLongPress"
      @toggle-keep-audio="handleToggleKeepAudio"
      @tags-updated="handleTaskTagsUpdated"
    />

    <!-- 批次編輯：底部浮動工具列 -->
    <BatchEditToolbar
      v-if="isBatchEditMode"
      :selected-task-ids="selectedTaskIds"
      :tasks="sortedTasks"
      :all-tags="allTags"
      @select-all="handleSelectAll"
      @deselect-all="handleDeselectAll"
      @batch-delete="handleBatchDelete"
      @batch-tags-add="handleBatchTagsAdd"
      @batch-tags-remove="handleBatchTagsRemove"
      @exit="exitBatchEditMode"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../utils/api'
import { useTaskTags } from '../../composables/task/useTaskTags'
import { taskService } from '../../api/services'
import { useAuthStore } from '../../stores/auth'
import TaskFilterBar from './TaskFilterBar.vue'
import BatchEditToolbar from './BatchEditToolbar.vue'
import TaskGrid from './TaskGrid.vue'
import RulerPagination from '../common/RulerPagination.vue'

const { t: $t } = useI18n()
const { fetchTagColors, tagsData } = useTaskTags($t)
const authStore = useAuthStore()

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
  // 批次編輯時鎖定換頁，避免改變列表內容
  if (isBatchEditMode.value) return
  emit('page-change', newPage)
}

// SessionStorage 鍵值
const STORAGE_KEY_FILTER_TAGS = 'taskList_filterTags'
const STORAGE_KEY_TASK_TYPE = 'taskList_taskType'
const STORAGE_KEY_SEARCH_QUERY = 'taskList_searchQuery'
const STORAGE_KEY_PRESERVE_FLAG = 'taskList_preserveFilters'

// 與後端 MAX_NAME_QUERY_LENGTH 對齊（後端仍會截斷，這裡只是提早擋住）
const MAX_SEARCH_LENGTH = 100
// 邊打邊送會把每個字元都變成一次查詢，debounce 收斂成一次
const SEARCH_DEBOUNCE_MS = 300

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
      const savedQuery = sessionStorage.getItem(STORAGE_KEY_SEARCH_QUERY)

      if (savedTags) {
        selectedFilterTags.value = JSON.parse(savedTags)
      }
      if (savedType) {
        selectedTaskType.value = savedType
      }
      if (savedQuery) {
        // 直接寫 debouncedSearchQuery，避免 restore 觸發一次多餘的 debounce 查詢
        searchQuery.value = savedQuery
        debouncedSearchQuery.value = savedQuery
      }
    } else {
      // 不保留，清除篩選狀態
      sessionStorage.removeItem(STORAGE_KEY_FILTER_TAGS)
      sessionStorage.removeItem(STORAGE_KEY_TASK_TYPE)
      sessionStorage.removeItem(STORAGE_KEY_SEARCH_QUERY)
    }
  } catch (error) {
    console.error('Failed to restore filter state:', error)
  }
}

// State
const selectedFilterTags = ref([])
const selectedTaskType = ref('all') // 任務類型篩選：'all', 'paragraph', 'subtitle', 'has_audio'
const searchQuery = ref('')          // 輸入框即時值
const debouncedSearchQuery = ref('') // 實際送給後端的值
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

// 搜尋輸入 debounce：打字停下 300ms 才更新 debouncedSearchQuery 觸發查詢。
// 清空時不等待，立刻還原完整列表。
let searchDebounceTimer = null
watch(searchQuery, (newQuery) => {
  clearTimeout(searchDebounceTimer)

  const trimmed = (newQuery || '').trim()
  if (!trimmed) {
    debouncedSearchQuery.value = ''
    return
  }

  searchDebounceTimer = setTimeout(() => {
    debouncedSearchQuery.value = trimmed
  }, SEARCH_DEBOUNCE_MS)
})

watch(debouncedSearchQuery, (newQuery) => {
  try {
    if (newQuery) {
      sessionStorage.setItem(STORAGE_KEY_SEARCH_QUERY, newQuery)
    } else {
      sessionStorage.removeItem(STORAGE_KEY_SEARCH_QUERY)
    }
  } catch (error) {
    console.error('Failed to save search query:', error)
  }
})

onBeforeUnmount(() => {
  clearTimeout(searchDebounceTimer)
})

// 發送篩選變更事件的函數
const emitFilterChange = () => {
  const filterData = {
    taskType: null,
    tags: selectedFilterTags.value,
    hasAudio: null,
    query: debouncedSearchQuery.value
  }

  // 根據選擇的類型設置篩選條件
  if (selectedTaskType.value === 'has_audio') {
    filterData.hasAudio = true
  } else if (selectedTaskType.value !== 'all') {
    filterData.taskType = selectedTaskType.value
  }

  emit('filter-change', filterData)
}

// 監聽篩選條件變化，通知父組件
// 注意：不使用 immediate，初始觸發由 onMounted 控制
watch([selectedTaskType, selectedFilterTags, debouncedSearchQuery], emitFilterChange, { deep: true })

// Computed
// 從共享 tagsData 推導（避免額外打一次 /tags）
const allTags = computed(() => tagsData.value.map(t => t.name))

// 目前是否有任何篩選條件。TaskGrid 用它區分「新使用者」與「篩選後為空」——
// 少了這個判斷，老使用者只要搜不到東西就會看到「上傳第一個音檔」引導。
const hasActiveFilters = computed(() =>
  selectedTaskType.value !== 'all' ||
  selectedFilterTags.value.length > 0 ||
  !!debouncedSearchQuery.value
)

const sortedTasks = computed(() => {
  // 後端已經處理了 task_type 和 tags 篩選，且預設按 created_at desc 排序。
  // 這裡把任務分三層：processing 最上、pending 第二，
  // 其餘狀態（completed / failed / cancelled）維持後端原本的時間順序。
  // Array.sort 在 ES2019+ 是穩定排序，同 priority 的內部順序不會被打亂。
  const priority = (status) => {
    if (status === 'processing') return 0
    if (status === 'pending') return 1
    return 2
  }
  return [...props.tasks].sort((a, b) => priority(a.status) - priority(b.status))
})

// Methods - Batch Mode
function toggleBatchEditMode() {
  if (isBatchEditMode.value) {
    exitBatchEditMode()
  } else {
    isBatchEditMode.value = true
  }
}

function exitBatchEditMode() {
  isBatchEditMode.value = false
  selectedTaskIds.value = new Set()
}

// 手機：長按卡片進入批次選取模式並勾選該卡（入口取代原「編輯」頁籤）
function handleLongPress(taskId) {
  if (!isBatchEditMode.value) {
    isBatchEditMode.value = true
  }
  if (!selectedTaskIds.value.has(taskId)) {
    handleToggleSelection(taskId)
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
      alert($t('taskList.errorKeepAudioLimit', { n: authStore.maxKeepAudio }))
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
    // 指派時可能隱含建立了新 tag：刷新共享 tagsData，讓篩選列/picker 立即看到
    fetchTagColors()
  } catch (error) {
    console.error($t('taskList.errorUpdateTags') + ':', error)
    alert($t('taskList.errorUpdateTagsFull', { message: error.response?.data?.detail || error.message }))
  }
}

// Methods - Tag Events
function handleTagRenamed() {
  // 標籤重命名後刷新（tagsData 已由 composable 內部同步，僅需通知 parent 重抓 task）
  emit('refresh')
  fetchTagColors()
}

function handleTagColorChanged() {
  // 顏色變更後無需刷新，因為 composable 已更新
}

async function handleTagsReordered() {
  // 標籤順序變更後重新獲取標籤數據，確保順序同步
  await fetchTagColors()
}

// Lifecycle
onMounted(() => {
  restoreFilterState()
  // 在恢復篩選狀態後，手動觸發一次 filter-change 來載入數據
  // 這確保使用恢復後的篩選條件，而非初始值
  emitFilterChange()
  fetchTagColors()
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

/* FilterBar 的上方間距改由 .task-list-header 統一負責（見該規則的註解） */
.task-list :deep(.filter-section) {
  margin-top: 0;
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

.task-list.task-type-has_audio :deep(.tasks) {
  padding: 10px;
  border-radius: 8px;
  position: relative;
  z-index: 5;
}

/* empty-state 統一使用 --upload-bg，在頁籤之上、.tasks 之下 */
.task-list.task-type-all :deep(.empty-state),
.task-list.task-type-paragraph :deep(.empty-state),
.task-list.task-type-subtitle :deep(.empty-state),
.task-list.task-type-has_audio :deep(.empty-state) {
  background-color: var(--upload-bg);
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

/* 批次編輯時為底部浮動工具列預留空間，避免遮住最後一筆任務 */
.task-list.batch-edit-active {
  padding-bottom: 120px;
}

/* 批次編輯時鎖定篩選與換頁：灰化 + 禁止互動，避免改變列表內容 */
.task-list.batch-edit-active :deep(.filter-section),
.task-list.batch-edit-active .pagination-wrapper {
  pointer-events: none;
  filter: grayscale(1);
  opacity: 0.5;
}

/* 非批次的類型頁籤一併灰化鎖定（批次頁籤保留可點以退出） */
.task-list.batch-edit-active .tab-btn:disabled {
  pointer-events: none;
  filter: grayscale(1);
  cursor: not-allowed;
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
  z-index: 101;
}

/* 頂部列：TaskFilterBar（可能因無標籤而不渲染）+ 搜尋框。
   filter-section 自己有 padding/margin，這裡只負責把兩者排成一列。 */
.task-list-header {
  display: flex;
  align-items: center;
  gap: 12px;
  /* 間距掛在整列上，不掛在 filter-section——否則兩個子元素的垂直基準不同，
     align-items:center 會把搜尋框對齊到含 margin 的高度中心而歪掉 */
  margin-top: 40px;
}

/* TaskFilterBar 撐滿剩餘空間，把搜尋框推到最右；
   沒有標籤時 filter-section 不渲染，搜尋框靠 margin-left:auto 仍然靠右 */
.task-list-header :deep(.filter-section) {
  flex: 1;
  min-width: 0;
}

/* 名稱搜尋框（桌機；手機在下方 media query 隱藏，搜尋入口改走 MobileHeader） */
.task-search {
  margin-left: auto;
  /* 右緣對齊正下方的分頁控制（兩者都貼齊容器右緣），讓上下兩列的
     右側元素連成同一條線；標籤的右邊界會隨 filter-section 伸縮，對不齊 */
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid rgba(var(--color-text-dark-rgb), 0.2);
  border-radius: 16px;
  background: transparent;
  transition: border-color 0.2s ease;
}

.task-search:focus-within {
  border-color: var(--color-teal);
}

.task-search-icon {
  flex-shrink: 0;
  color: rgba(var(--color-text-dark-rgb), 0.45);
}

.task-search-input {
  width: 160px;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: var(--nav-text);
}

.task-search-input::placeholder {
  color: rgba(var(--color-text-dark-rgb), 0.4);
}

.task-search-input:disabled {
  cursor: not-allowed;
}

/* type="search" 的原生清除鈕外觀各家瀏覽器不一致，關掉改用自訂按鈕 */
.task-search-input::-webkit-search-cancel-button {
  -webkit-appearance: none;
  appearance: none;
}

.task-search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  padding: 2px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: rgba(var(--color-text-dark-rgb), 0.45);
  border-radius: 50%;
}

.task-search-clear:hover {
  color: var(--nav-text);
  background: rgba(var(--color-text-dark-rgb), 0.08);
}

/* 批次編輯模式：與頁籤/分頁一致灰化鎖定 */
.task-list.batch-edit-active .task-search {
  pointer-events: none;
  filter: grayscale(1);
  opacity: 0.5;
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

/* 篩選頁籤 icon 只給手機版用（桌機維持純文字外觀），768px 以下改 display:block */
.tab-icon {
  display: none;
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
.task-list.batch-edit-active .tab-btn.tab-subtitle,
.task-list.batch-edit-active .tab-btn.tab-has-audio {
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

/* === 響應式設計 === */

/* 平板以下 (768px) */
@media (max-width: 768px) {
  /* 底部固定頁籤列（52px + safe-area）一律會蓋住內容區，先留一份基本空間；
     有分頁時（浮動 RulerPagination 在頁籤列之上）再加碼避免遮住最後一筆任務 */
  .task-list {
    padding-bottom: calc(52px + env(safe-area-inset-bottom, 0px) + 12px);
  }

  .task-list.has-pagination {
    /* 頁籤列 52px + 浮動分頁窗（~64px，浮在頁籤列上方）+ 間距，
       不足會讓最後一筆任務被分頁窗蓋住（375px 實測定案） */
    padding-bottom: calc(52px + env(safe-area-inset-bottom, 0px) + 110px);
  }

  /* 批次工具列在 mobile 浮於底部導覽列之上，需更多底部空間 */
  .task-list.batch-edit-active {
    padding-bottom: 200px;
  }

  /* 手機版切頁是 position:fixed 浮窗；批次編輯時直接隱藏，
     避免與底部工具列重疊、或被祖層 filter 影響定位而跑到上方 */
  .task-list.batch-edit-active :deep(.pagination) {
    display: none;
  }

  /* 任務類型頁籤（含編輯）改為固定在畫面底部的列，五顆均分 */
  .task-type-tabs {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 1000;
    flex-wrap: nowrap;
    align-items: stretch;
    gap: 0;
    margin: 0;
    padding: 0 calc(4px + env(safe-area-inset-right, 0px)) env(safe-area-inset-bottom, 0px) calc(4px + env(safe-area-inset-left, 0px));
    height: calc(52px + env(safe-area-inset-bottom, 0px));
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.1);
  }

  :root[data-theme="dark"] .task-type-tabs {
    background: rgba(40, 40, 40, 0.95);
  }

  .tab-btn {
    flex: 1;
    margin: 0;
    padding: 4px 2px;
    font-size: 11px;
    white-space: nowrap;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    color: var(--main-text);
    /* 確保觸控友好 */
    min-height: 44px;
  }

  /* 手機版頁籤 icon（桌機隱藏以維持原外觀，見組件頂層 .tab-icon 規則） */
  .tab-icon {
    display: block;
  }

  /* 手機不放「編輯」頁籤（批次模式改由長按卡片進入），篩選列變純篩選 */
  .tab-btn.tab-batch-edit {
    display: none;
  }

  /* icon 用 main-text（含編輯的鉛筆）；active 膠囊內跟著標籤文字色 */
  .tab-btn svg {
    color: var(--main-text);
  }

  .tab-btn.active svg {
    color: var(--nav-recent-text);
  }

  /* 選取效果沿用原底部導覽（nav-link.active）的膠囊樣式，讓作用中的篩選一目了然 */
  .tab-btn.active {
    transform: none;
    border-bottom: none;
    background: var(--nav-active-bg);
    color: var(--nav-recent-text);
    border-radius: 8px;
  }

  /* 批次編輯頁籤 active 也用同一套膠囊（覆蓋桌機的純變色規則） */
  .tab-btn.tab-batch-edit.active {
    color: var(--nav-recent-text);
  }

  /* 分頁列不再參與底部固定頁籤的 flex 排版：RulerPagination 本身已是 position:fixed
     浮窗（見 RulerPagination.vue），用 display:contents 讓 wrapper 這層盒子消失、
     但仍讓子元件正常渲染／保有自己的 fixed 定位 */
  .pagination-wrapper {
    display: contents;
  }

  /* 手機搜尋入口是 MobileHeader 那顆按鈕（另案接上），這裡不顯示桌機搜尋框。
     隱藏後 .task-list-header 只剩 TaskFilterBar，維持原本的單欄排版 */
  .task-search {
    display: none;
  }

  /* FilterBar 間距調整 */
  /* 手機間距同樣掛在整列上（桌機是 40px，見 .task-list-header） */
  .task-list-header {
    margin-top: 20px;
  }

  /* 任務網格間距調整 */
  .task-list.task-type-all :deep(.tasks),
  .task-list.task-type-paragraph :deep(.tasks),
  .task-list.task-type-subtitle :deep(.tasks),
  .task-list.task-type-has_audio :deep(.tasks) {
    padding: 8px;
  }
}

/* 小手機 (480px) */
@media (max-width: 480px) {
  .task-list.has-pagination {
    padding-bottom: 72px;
  }

  .tab-btn {
    padding: 4px 1px;
    margin: 0;
    font-size: 10px;
  }

  /* 五顆頁籤（含編輯）在小手機一律保留文字，只縮小字級，不再隱藏 */
  .tab-btn.tab-batch-edit {
    padding: 4px 1px;
  }

  /* 任務網格更緊湊 */
  .task-list.task-type-all :deep(.tasks),
  .task-list.task-type-paragraph :deep(.tasks),
  .task-list.task-type-subtitle :deep(.tasks),
  .task-list.task-type-has_audio :deep(.tasks) {
    padding: 4px;
  }

  /* 批次編輯模式調整 */
  .task-list :deep(.tasks.batch-mode) {
    padding: 12px !important;
  }
}
</style>
