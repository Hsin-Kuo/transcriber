<template>
  <div class="batch-toolbar">
    <!-- 標題列 -->
    <div class="batch-toolbar-header">
      <div class="batch-header-left">
        <button class="btn-batch-select-all" @click="handleToggleSelectAll">
          <input
            type="checkbox"
            :checked="selectedTaskIds.size === tasks.length && tasks.length > 0"
            :indeterminate="selectedTaskIds.size > 0 && selectedTaskIds.size < tasks.length"
            readonly
          />
          <span>
            {{ selectedTaskIds.size === tasks.length && tasks.length > 0
              ? $t('taskList.deselectAll')
              : $t('taskList.selectAll') }}
          </span>
        </button>
        <span class="batch-selection-count">
          {{ $t('taskList.selectedTasks', { count: selectedTaskIds.size, total: tasks.length }) }}
        </span>
      </div>

      <div class="batch-header-right">
        <button
          v-if="selectedTaskIds.size > 0"
          class="btn-batch-action btn-batch-delete"
          @click="handleBatchDelete"
          :title="$t('taskList.batchDeleteTitle', { count: selectedTaskIds.size })"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="3 6 5 6 21 6"></polyline>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
          {{ $t('taskList.batchDelete', { count: selectedTaskIds.size }) }}
        </button>
      </div>
    </div>

    <!-- 批次操作區域（僅在有選中任務時顯示） -->
    <div v-if="selectedTaskIds.size > 0" class="batch-actions">
      <!-- 緊湊型標籤管理區域 -->
      <div class="batch-tags-section-compact" :class="{ 'collapsed': isCollapsed }">
        <!-- 標籤區域標題和摺疊按鈕 -->
        <div class="batch-tags-header">
          <div class="batch-tags-info">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
              <line x1="7" y1="7" x2="7.01" y2="7"></line>
            </svg>
            <span class="tags-title">{{ $t('taskList.batchTagEdit') }}</span>
            <span class="tags-stats">
              {{ $t('taskList.tagsStats', {
                common: selectedTasksTagsComputed.commonTags.length,
                candidate: selectedTasksTagsComputed.candidateTags.length
              }) }}
            </span>
          </div>
          <button
            class="btn-collapse"
            @click="isCollapsed = !isCollapsed"
            :title="isCollapsed ? $t('taskList.expand') : $t('taskList.collapse')"
          >
            {{ isCollapsed ? '▼' : '▲' }}
          </button>
        </div>

        <!-- 標籤列表（可摺疊） -->
        <div v-show="!isCollapsed" class="batch-tags-content">
          <!-- 統一的標籤列表 -->
          <div v-if="unifiedTagsListComputed.length > 0" class="tags-pills-container">
            <div class="tags-pills-list">
              <button
                v-for="item in unifiedTagsListComputed"
                :key="item.tag"
                class="tag-pill"
                :class="{ 'tag-added': item.isAdded, 'tag-available': !item.isAdded }"
                :style="{ color: getTagColor(item.tag) }"
                @click="item.isAdded ? handleQuickRemoveTag(item.tag) : handleQuickAddTag(item.tag)"
                :title="item.isAdded
                  ? $t('taskList.clickToRemoveTag', { tag: item.tag })
                  : $t('taskList.clickToAddTag', { tag: item.tag })"
              >
                <svg class="pill-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <template v-if="item.isAdded">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </template>
                  <template v-else>
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                  </template>
                </svg>
                <span>{{ item.tag }}</span>
              </button>
            </div>
          </div>

          <!-- 無標籤提示 -->
          <div v-else class="batch-tags-empty">
            {{ $t('taskList.noAvailableTags') }}
          </div>

          <!-- 手動輸入 -->
          <div class="batch-manual-input-compact">
            <input
              type="text"
              v-model="manualTagInput"
              :placeholder="$t('taskList.manualTagInputPlaceholder')"
              class="manual-input-field"
              @keydown.enter="handleManualAddTags"
            />
            <button
              class="btn-manual-add"
              @click="handleManualAddTags"
              :disabled="!manualTagInput.trim()"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 5v14M5 12h14"></path>
              </svg>
              {{ $t('taskList.addButton') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTaskTags } from '../../composables/task/useTaskTags'

const { t: $t } = useI18n()
const { getTagColor } = useTaskTags($t)

// Props
const props = defineProps({
  selectedTaskIds: {
    type: Set,
    required: true
  },
  tasks: {
    type: Array,
    required: true
  },
  allTags: {
    type: Array,
    required: true
  }
})

// Emits
const emit = defineEmits([
  'update:selectedTaskIds',
  'select-all',
  'deselect-all',
  'batch-delete',
  'batch-tags-add',
  'batch-tags-remove'
])

// State
const isCollapsed = ref(true)
const manualTagInput = ref('')

// Computed
const selectedTasksTagsComputed = computed(() => {
  if (props.selectedTaskIds.size === 0) {
    return {
      commonTags: [],
      candidateTags: []
    }
  }

  // 獲取所有選中的任務
  const selectedTasks = props.tasks.filter(t => props.selectedTaskIds.has(t.task_id))

  if (selectedTasks.length === 0) {
    return { commonTags: [], candidateTags: [] }
  }

  // 收集所有選中任務的標籤
  const allTagsMap = new Map() // tag -> count

  selectedTasks.forEach(task => {
    const tags = task.tags || []
    tags.forEach(tag => {
      allTagsMap.set(tag, (allTagsMap.get(tag) || 0) + 1)
    })
  })

  // 所有任務都有的標籤
  const commonTags = Array.from(allTagsMap.entries())
    .filter(([tag, count]) => count === selectedTasks.length)
    .map(([tag]) => tag)

  // 候選標籤 = 部分任務有的標籤 + 系統中的其他標籤（但不包括 commonTags）
  const partialTags = Array.from(allTagsMap.entries())
    .filter(([tag, count]) => count < selectedTasks.length)
    .map(([tag]) => tag)

  const otherTags = props.allTags.filter(tag =>
    !commonTags.includes(tag) && !partialTags.includes(tag)
  )

  const candidateTags = [...partialTags, ...otherTags]

  return { commonTags, candidateTags }
})

const unifiedTagsListComputed = computed(() => {
  const { commonTags, candidateTags } = selectedTasksTagsComputed.value

  // 合併標籤並標記狀態
  const tagsList = [
    ...commonTags.map(tag => ({ tag, isAdded: true })),
    ...candidateTags.map(tag => ({ tag, isAdded: false }))
  ]

  // 排序：已加入的在前，然後按標籤名稱排序
  return tagsList.sort((a, b) => {
    if (a.isAdded !== b.isAdded) {
      return a.isAdded ? -1 : 1
    }
    return a.tag.localeCompare(b.tag)
  })
})

// Methods
function handleToggleSelectAll() {
  if (props.selectedTaskIds.size === props.tasks.length) {
    emit('deselect-all')
  } else {
    emit('select-all')
  }
}

function handleBatchDelete() {
  emit('batch-delete')
}

function handleQuickAddTag(tag) {
  emit('batch-tags-add', [tag])
}

function handleQuickRemoveTag(tag) {
  emit('batch-tags-remove', [tag])
}

function handleManualAddTags() {
  if (!manualTagInput.value.trim()) {
    return
  }

  const tags = manualTagInput.value.split(',').map(t => t.trim()).filter(t => t)
  if (tags.length > 0) {
    emit('batch-tags-add', tags)
    manualTagInput.value = ''
  }
}
</script>

<style scoped>
/* 從 TaskList.vue 複製批次工具列的 CSS */
.batch-toolbar {
  background: rgba(var(--color-primary-rgb), 0.05);
  border: 1px solid rgba(var(--color-primary-rgb), 0.15);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 20px;
}

.batch-toolbar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.batch-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.btn-batch-select-all {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: white;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 13px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.8);
}

.btn-batch-select-all:hover {
  background: rgba(var(--color-primary-rgb), 0.05);
  border-color: rgba(var(--color-primary-rgb), 0.5);
}

.btn-batch-select-all input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.batch-selection-count {
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  font-weight: 500;
}

.batch-header-right {
  display: flex;
  gap: 12px;
}

.btn-batch-action {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-batch-delete {
  background: rgba(var(--color-danger-rgb), 0.15);
  color: var(--color-danger);
}

.btn-batch-delete:hover {
  background: rgba(var(--color-danger-rgb), 0.25);
  transform: translateY(-1px);
}

/* 批次操作區域 */
.batch-actions {
  margin-top: 16px;
}

/* 標籤管理區域 */
.batch-tags-section-compact {
  background: white;
  border: 1px solid rgba(var(--color-primary-rgb), 0.2);
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.3s;
}

.batch-tags-section-compact.collapsed {
  /* 摺疊狀態的樣式 */
}

.batch-tags-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: rgba(var(--color-teal-rgb), 0.05);
  border-bottom: 1px solid rgba(var(--color-primary-rgb), 0.1);
  cursor: pointer;
}

.batch-tags-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.batch-tags-info svg {
  color: var(--color-teal);
}

.tags-title {
  font-size: 13px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.8);
}

.tags-stats {
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb), 0.5);
  padding: 2px 8px;
  background: rgba(var(--color-teal-rgb), 0.1);
  border-radius: 4px;
}

.btn-collapse {
  padding: 4px 8px;
  background: none;
  border: none;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.btn-collapse:hover {
  color: rgba(var(--color-text-dark-rgb), 0.9);
}

/* 標籤內容 */
.batch-tags-content {
  padding: 16px;
}

.tags-pills-container {
  margin-bottom: 16px;
}

.tags-pills-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1.5px solid currentColor;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  background: white;
}

.tag-pill:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

.tag-pill.tag-added {
  background: currentColor;
  color: white !important;
}

.tag-pill.tag-available {
  background: rgba(255, 255, 255, 0.9);
}

.pill-icon {
  width: 14px;
  height: 14px;
}

.batch-tags-empty {
  padding: 20px;
  text-align: center;
  color: rgba(var(--color-text-dark-rgb), 0.5);
  font-size: 13px;
}

/* 手動輸入 */
.batch-manual-input-compact {
  display: flex;
  gap: 8px;
}

.manual-input-field {
  flex: 1;
  padding: 8px 12px;
  font-size: 13px;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 6px;
  transition: all 0.2s;
}

.manual-input-field:focus {
  outline: none;
  border-color: rgba(var(--color-primary-rgb), 0.5);
}

.btn-manual-add {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: rgba(var(--color-primary-rgb), 0.15);
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 6px;
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-manual-add:hover:not(:disabled) {
  background: rgba(var(--color-primary-rgb), 0.25);
  transform: translateY(-1px);
}

.btn-manual-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
