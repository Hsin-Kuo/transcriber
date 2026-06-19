<template>
  <Teleport to="body">
    <div class="batch-float-toolbar">
      <!-- 標籤編輯展開區（位於工具列上方） -->
      <transition name="batch-panel">
        <div v-if="showTagEditor && selectedCount > 0" class="batch-tag-editor">
          <div class="editor-title">
            {{ $t('taskList.applyTagsToTasks', { count: selectedCount }) }}
          </div>

          <div class="editor-dropdown" ref="dropdownRef">
            <button
              class="dropdown-trigger"
              :class="{ open: dropdownOpen }"
              @click="dropdownOpen = !dropdownOpen"
            >
              <span>{{ $t('taskList.selectTagToApply') }}</span>
              <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>

            <div v-if="dropdownOpen" class="dropdown-menu">
              <button
                v-for="item in tagOptions"
                :key="item.tag"
                class="dropdown-item"
                :class="{ 'is-common': item.isCommon }"
                @click="handleTagClick(item)"
              >
                <span class="tag-dot" :style="{ background: getTagColor(item.tag) }"></span>
                <span class="tag-name">{{ item.tag }}</span>
                <!-- common（全部任務都有）→ 移除（−）；否則 → 套用（＋） -->
                <svg v-if="item.isCommon" class="action-icon remove-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
                <svg v-else class="action-icon add-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
              </button>
              <div v-if="tagOptions.length === 0" class="dropdown-empty">
                {{ $t('taskList.noAvailableTags') }}
              </div>
            </div>
          </div>
        </div>
      </transition>

      <!-- 主工具列 -->
      <div class="batch-bar">
        <button
          class="batch-select-all"
          :title="allSelected ? $t('taskList.deselectAll') : $t('taskList.selectAll')"
          :aria-label="allSelected ? $t('taskList.deselectAll') : $t('taskList.selectAll')"
          @click="handleToggleSelectAll"
        >
          <input
            type="checkbox"
            :checked="allSelected"
            :indeterminate="someSelected"
            readonly
          />
          <span>{{ allSelected ? $t('taskList.deselectAll') : $t('taskList.selectAll') }}</span>
        </button>

        <span class="batch-count">
          {{ $t('taskList.batchSelectedCount', { count: selectedCount }) }}
        </span>

        <div class="batch-actions">
          <button
            class="batch-btn"
            :class="{ active: showTagEditor }"
            :disabled="selectedCount === 0"
            @click="toggleTagEditor"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
              <line x1="7" y1="7" x2="7.01" y2="7"></line>
            </svg>
            {{ $t('taskList.editTags') }}
          </button>

          <button
            class="batch-btn batch-btn-danger"
            :disabled="selectedCount === 0"
            @click="handleBatchDelete"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              <line x1="10" y1="11" x2="10" y2="17"></line>
              <line x1="14" y1="11" x2="14" y2="17"></line>
            </svg>
            {{ $t('taskList.delete') }}
          </button>

          <button class="batch-btn batch-btn-ghost batch-btn-icon" @click="handleExit" :title="$t('taskList.exit')" :aria-label="$t('taskList.exit')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
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
  'select-all',
  'deselect-all',
  'batch-delete',
  'batch-tags-add',
  'batch-tags-remove',
  'exit'
])

// State
const showTagEditor = ref(false)
const dropdownOpen = ref(false)
const dropdownRef = ref(null)

// Computed
const selectedCount = computed(() => props.selectedTaskIds.size)
const allSelected = computed(() => props.tasks.length > 0 && selectedCount.value === props.tasks.length)
const someSelected = computed(() => selectedCount.value > 0 && selectedCount.value < props.tasks.length)

// 標籤選項：標記 isCommon（= 所有選取任務都已擁有 → 點擊改為移除）
// 已套用（common）排在前面，其餘依字母排序
const tagOptions = computed(() => {
  const selectedTasks = props.tasks.filter(t => props.selectedTaskIds.has(t.task_id))
  if (selectedTasks.length === 0) return []

  const tagCount = new Map()
  selectedTasks.forEach(task => {
    (task.tags || []).forEach(tag => {
      tagCount.set(tag, (tagCount.get(tag) || 0) + 1)
    })
  })

  return props.allTags
    .map(tag => ({ tag, isCommon: tagCount.get(tag) === selectedTasks.length }))
    .sort((a, b) => {
      if (a.isCommon !== b.isCommon) return a.isCommon ? -1 : 1
      return a.tag.localeCompare(b.tag)
    })
})

// Methods
function handleToggleSelectAll() {
  emit(allSelected.value ? 'deselect-all' : 'select-all')
}

function toggleTagEditor() {
  showTagEditor.value = !showTagEditor.value
  if (!showTagEditor.value) dropdownOpen.value = false
}

function handleTagClick(item) {
  // 所有選取任務都已擁有 → 移除；否則 → 套用（新增）
  // 保持下拉開啟，方便連續操作；刷新後該標籤的 common 狀態會自動更新
  if (item.isCommon) {
    emit('batch-tags-remove', [item.tag])
  } else {
    emit('batch-tags-add', [item.tag])
  }
}

function handleBatchDelete() {
  emit('batch-delete')
}

function handleExit() {
  emit('exit')
}

// 點擊下拉外部時關閉
function handleClickOutside(event) {
  if (dropdownOpen.value && dropdownRef.value && !dropdownRef.value.contains(event.target)) {
    dropdownOpen.value = false
  }
}

onMounted(() => document.addEventListener('mousedown', handleClickOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', handleClickOutside))
</script>

<style scoped>
.batch-float-toolbar {
  position: fixed;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  z-index: 1100; /* 高於 mobile 底部導覽列 (1000) */
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  width: max-content;
  max-width: calc(100vw - 32px);
}

/* 主工具列 */
.batch-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 10px 16px;
  background: var(--color-bg-light, #fff);
  border: 1px solid rgba(var(--color-text-dark-rgb), 0.12);
  border-radius: 14px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
}

.batch-select-all {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--main-text);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s;
}

.batch-select-all:hover {
  background: rgba(var(--color-text-dark-rgb), 0.06);
}

.batch-select-all input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.batch-count {
  font-size: 14px;
  font-weight: 600;
  color: var(--main-text);
  white-space: nowrap;
  padding-left: 2px;
}

.batch-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.batch-btn:hover:not(:disabled) {
  background: rgba(var(--color-primary-rgb), 0.1);
}

.batch-btn.active {
  background: rgba(var(--color-primary-rgb), 0.16);
}

.batch-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.batch-btn-danger {
  color: var(--color-danger);
}

.batch-btn-danger:hover:not(:disabled) {
  background: rgba(var(--color-danger-rgb), 0.12);
}

.batch-btn-ghost {
  border: none;
  background: transparent;
  color: rgba(var(--color-text-dark-rgb), 0.7);
}

.batch-btn-ghost:hover:not(:disabled) {
  background: rgba(var(--color-text-dark-rgb), 0.06);
  color: var(--main-text);
}

/* 純圖示按鈕：方形、無多餘左右留白 */
.batch-btn-icon {
  padding: 8px;
  gap: 0;
}

/* 標籤編輯展開區 */
.batch-tag-editor {
  padding: 14px 16px;
  background: var(--color-bg-light, #fff);
  border: 1px solid rgba(var(--color-text-dark-rgb), 0.12);
  border-radius: 14px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
}

.editor-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--main-text);
  margin-bottom: 10px;
}

/* 下拉選單 */
.editor-dropdown {
  position: relative;
}

.dropdown-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-width: 240px;
  padding: 9px 12px;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 10px;
  background: var(--color-bg, #fff);
  color: var(--main-text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.dropdown-trigger:hover,
.dropdown-trigger.open {
  border-color: rgba(var(--color-primary-rgb), 0.5);
}

.chevron {
  flex-shrink: 0;
  color: rgba(var(--color-text-dark-rgb), 0.55);
  transition: transform 0.2s;
}

.dropdown-trigger.open .chevron {
  transform: rotate(180deg);
}

.dropdown-menu {
  position: absolute;
  left: 0;
  right: 0;
  bottom: calc(100% + 6px); /* 往上展開，因為工具列在底部 */
  max-height: 240px;
  overflow-y: auto;
  padding: 6px;
  background: var(--color-bg, #fff);
  border: 1px solid rgba(var(--color-text-dark-rgb), 0.12);
  border-radius: 10px;
  box-shadow: 0 -6px 24px rgba(0, 0, 0, 0.16);
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--main-text);
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s;
  text-align: left;
}

.dropdown-item:hover {
  background: rgba(var(--color-primary-rgb), 0.1);
}

/* 共用標籤（全部任務都有）非 hover 時以灰底標示「已套用」 */
.dropdown-item.is-common {
  background: rgba(var(--color-text-dark-rgb), 0.06);
}

.dropdown-item.is-common:hover {
  background: rgba(var(--color-danger-rgb), 0.1);
}

.dropdown-item .tag-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown-item .action-icon {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}

.dropdown-item:hover .action-icon {
  opacity: 1;
}

.dropdown-item .add-icon {
  color: var(--color-primary);
}

.dropdown-item .remove-icon {
  color: var(--color-danger);
}

.tag-dot {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.dropdown-empty {
  padding: 16px;
  text-align: center;
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.5);
}

/* 展開動畫 */
.batch-panel-enter-active,
.batch-panel-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.batch-panel-enter-from,
.batch-panel-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* === 響應式 === */
@media (max-width: 768px) {
  .batch-float-toolbar {
    bottom: calc(72px + env(safe-area-inset-bottom, 0px)); /* 避開底部導覽列 */
    left: 16px;
    right: 16px;
    transform: none;
    width: auto;
    max-width: none;
  }

  .batch-bar {
    justify-content: space-between;
    gap: 10px;
  }

  .batch-btn {
    padding: 8px 10px;
  }

  .dropdown-trigger {
    min-width: 0;
  }
}

@media (max-width: 480px) {
  .batch-bar {
    gap: 6px;
  }

  .batch-btn,
  .batch-count {
    font-size: 12px;
  }

  /* 螢幕太窄：隱藏全選文字，只留 checkbox（title/aria-label 仍保留） */
  .batch-select-all span {
    display: none;
  }

  .batch-select-all {
    padding: 6px;
  }
}
</style>
