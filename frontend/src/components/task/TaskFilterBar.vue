<template>
  <div v-if="allTags.length > 0" class="filter-section">
    <!-- 篩選圖標 -->
    <svg class="filter-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
    </svg>

    <!-- 標籤列表 -->
    <div class="filter-tags">
      <div
        v-for="(tag, index) in displayedTagsList"
        :key="tag"
        class="filter-tag-item"
        :class="{
          'editing': isEditing,
          'dragging': draggingIndex === index,
          'drag-over': dragOverIndex === index
        }"
        :draggable="isEditing"
        @dragstart="handleDragStart(index, $event)"
        @dragover.prevent="handleDragOver(index, $event)"
        @drop="handleDrop(index, $event)"
        @dragend="handleDragEnd"
      >
        <!-- 編輯模式：拖曳提示圖標 -->
        <div v-if="isEditing" class="drag-handle" :title="$t('taskList.dragToReorder')">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="8" y1="6" x2="21" y2="6"></line>
            <line x1="8" y1="12" x2="21" y2="12"></line>
            <line x1="8" y1="18" x2="21" y2="18"></line>
            <line x1="3" y1="6" x2="3.01" y2="6"></line>
            <line x1="3" y1="12" x2="3.01" y2="12"></line>
            <line x1="3" y1="18" x2="3.01" y2="18"></line>
          </svg>
        </div>

        <!-- 編輯模式：可點擊編輯標籤文字 -->
        <input
          v-if="isEditing && editingTag === tag"
          type="text"
          class="filter-tag-input"
          v-model="editingTagText"
          @blur="finishEditingTag"
          @keyup.enter="finishEditingTag"
          @keyup.esc="cancelEditingTag"
          ref="tagInput"
          :style="{
            borderColor: getTagColor(tag),
            color: getTagColor(tag)
          }"
        />

        <!-- 標籤按鈕 -->
        <button
          v-else
          class="filter-tag-btn"
          :class="{ active: selectedTags.includes(tag) }"
          :style="{
            '--tag-color': getTagColor(tag),
            color: getTagColor(tag)
          }"
          @click="isEditing ? startEditingTag(tag) : toggleTag(tag)"
          :title="isEditing ? $t('taskList.clickToEditName') : ''"
        >
          {{ tag }}
        </button>

        <!-- 編輯模式：顏色選擇器按鈕 -->
        <div v-if="isEditing" class="tag-color-picker-wrapper">
          <button
            :ref="el => setColorPickerButtonRef(tag, el)"
            class="btn-color-picker"
            :title="$t('taskList.setTagColor', { tag })"
            @click="handleToggleColorPicker(tag)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"></path>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- 操作按鈕 -->
    <div class="filter-header-actions">
      <!-- 編輯按鈕 -->
      <button
        v-if="!isEditing"
        class="btn-edit-filter"
        @click="startEditing"
        :title="$t('taskList.editTags')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
        </svg>
      </button>

      <!-- 保存按鈕 -->
      <button
        v-else
        class="btn-save-filter"
        @click="saveEditing"
        :title="$t('taskList.save')"
      >
        ✓
      </button>

      <!-- 清除篩選按鈕 -->
      <button
        v-if="selectedTags.length > 0 && !isEditing"
        class="btn-clear-filter"
        @click="clearFilter"
        :title="$t('taskList.clearFilter')"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
        </svg>
      </button>
    </div>

    <!-- 顏色選擇器彈出窗口 -->
    <ColorPickerPopup
      v-model:isOpen="showColorPicker"
      :current-color="currentColor"
      :position="colorPickerPosition"
      :target-tag="colorPickerTag"
      @color-selected="handleColorSelected"
    />
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTaskTags } from '../../composables/task/useTaskTags'
import ColorPickerPopup from './ColorPickerPopup.vue'

const { t: $t } = useI18n()
const { getTagColor, updateTagColor, renameTag, saveTagOrder, getTagIds } = useTaskTags($t)

// Props
const props = defineProps({
  allTags: {
    type: Array,
    required: true
  },
  selectedTags: {
    type: Array,
    default: () => []
  },
  isEditing: {
    type: Boolean,
    default: false
  },
  customTagOrder: {
    type: Array,
    default: () => []
  },
  tasks: {
    type: Array,
    default: () => []
  }
})

// Emits
const emit = defineEmits([
  'update:selectedTags',
  'update:isEditing',
  'update:customTagOrder',
  'tag-renamed',
  'tag-color-changed',
  'tags-reordered',
  'refresh'
])

// State
const editingTagOrder = ref([])
const draggingIndex = ref(null)
const dragOverIndex = ref(null)
const editingTag = ref(null)
const editingTagText = ref('')
const isRenamingTag = ref(false)
const tagInput = ref(null)

// Color picker state
const showColorPicker = ref(false)
const colorPickerTag = ref(null)
const colorPickerPosition = ref({})
const colorPickerButtons = ref({})

// Computed
const displayedTagsList = computed(() => {
  if (props.isEditing && editingTagOrder.value.length > 0) {
    return editingTagOrder.value
  }
  return props.allTags
})

const currentColor = computed(() => {
  if (colorPickerTag.value) {
    return getTagColor(colorPickerTag.value)
  }
  return '#667eea'
})

// Methods
function toggleTag(tag) {
  const newSelectedTags = [...props.selectedTags]
  const index = newSelectedTags.indexOf(tag)
  if (index > -1) {
    newSelectedTags.splice(index, 1)
  } else {
    newSelectedTags.push(tag)
  }
  emit('update:selectedTags', newSelectedTags)
}

function clearFilter() {
  emit('update:selectedTags', [])
}

function startEditing() {
  emit('update:isEditing', true)
  editingTagOrder.value = [...props.allTags]
}

async function saveEditing() {
  // 保存標籤順序到後端
  try {
    const tagIds = getTagIds(editingTagOrder.value)
    await saveTagOrder(tagIds)
    emit('update:customTagOrder', [...editingTagOrder.value])
    emit('tags-reordered')
  } catch (error) {
    alert($t('taskList.errorSaveTagOrderFull', { message: error.message }))
  }

  emit('update:isEditing', false)
  showColorPicker.value = false
}

// 拖放排序
function handleDragStart(index, event) {
  draggingIndex.value = index
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', index.toString())
}

function handleDragOver(index, event) {
  if (draggingIndex.value === null || draggingIndex.value === index) {
    return
  }
  dragOverIndex.value = index
}

function handleDrop(index) {
  if (draggingIndex.value === null || draggingIndex.value === index) {
    return
  }

  // 重新排序
  const newOrder = [...editingTagOrder.value]
  const draggedItem = newOrder[draggingIndex.value]

  // 移除拖動的項目
  newOrder.splice(draggingIndex.value, 1)
  // 插入到新位置
  newOrder.splice(index, 0, draggedItem)

  editingTagOrder.value = newOrder
  draggingIndex.value = null
  dragOverIndex.value = null
}

function handleDragEnd() {
  draggingIndex.value = null
  dragOverIndex.value = null
}

// 標籤重命名
function startEditingTag(tag) {
  if (isRenamingTag.value) {
    return
  }
  editingTag.value = tag
  editingTagText.value = tag
  nextTick(() => {
    const inputs = document.querySelectorAll('.filter-tag-input')
    inputs.forEach(input => input.focus())
  })
}

async function finishEditingTag() {
  if (isRenamingTag.value) {
    return
  }

  const oldTag = editingTag.value
  const newTag = editingTagText.value.trim()

  if (!newTag || newTag === oldTag) {
    cancelEditingTag()
    return
  }

  // 檢查新標籤名稱是否已存在
  const currentTags = props.isEditing && editingTagOrder.value.length > 0
    ? editingTagOrder.value
    : props.allTags
  const otherTags = currentTags.filter(tag => tag !== oldTag)
  if (otherTags.includes(newTag)) {
    alert($t('taskList.errorTagExists', { tag: newTag }))
    return
  }

  isRenamingTag.value = true

  try {
    await renameTag(oldTag, newTag, props.tasks)

    // 更新編輯中的標籤順序
    if (editingTagOrder.value.includes(oldTag)) {
      const index = editingTagOrder.value.indexOf(oldTag)
      editingTagOrder.value[index] = newTag
    }

    // 更新選中的篩選標籤
    if (props.selectedTags.includes(oldTag)) {
      const newSelectedTags = [...props.selectedTags]
      const index = newSelectedTags.indexOf(oldTag)
      newSelectedTags[index] = newTag
      emit('update:selectedTags', newSelectedTags)
    }

    emit('tag-renamed')
    emit('refresh')
  } catch (error) {
    alert($t('taskList.errorRenameTagFull', { message: error.message }))
  } finally {
    isRenamingTag.value = false
  }

  cancelEditingTag()
}

function cancelEditingTag() {
  editingTag.value = null
  editingTagText.value = ''
  isRenamingTag.value = false
}

// 顏色選擇器
function setColorPickerButtonRef(tag, el) {
  if (el) {
    colorPickerButtons.value[tag] = el
  }
}

function handleToggleColorPicker(tag) {
  if (colorPickerTag.value === tag) {
    showColorPicker.value = false
    colorPickerTag.value = null
    colorPickerPosition.value = {}
  } else {
    colorPickerTag.value = tag
    showColorPicker.value = true

    // 計算彈窗位置
    const button = colorPickerButtons.value[tag]
    if (button) {
      const rect = button.getBoundingClientRect()
      const popupWidth = 220
      const popupHeight = 240

      // 預設在按鈕下方
      let top = rect.bottom + 8
      let left = rect.left

      // 如果右邊空間不夠，向左調整
      if (left + popupWidth > window.innerWidth) {
        left = window.innerWidth - popupWidth - 16
      }

      // 如果下方空間不夠，改在上方
      if (top + popupHeight > window.innerHeight) {
        top = rect.top - popupHeight - 8
      }

      colorPickerPosition.value = {
        top: `${top}px`,
        left: `${left}px`
      }
    }
  }
}

async function handleColorSelected({ tag, color }) {
  try {
    await updateTagColor(tag, color)
    emit('tag-color-changed', { tag, color })
  } catch (error) {
    console.error('Error updating tag color:', error)
  }
}
</script>

<style scoped>
/* 篩選列樣式 */
.filter-section {
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-icon {
  color: rgba(var(--color-teal-rgb), 0.8);
  flex-shrink: 0;
}

.filter-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}

.filter-tag-item {
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
  position: relative;
}

.filter-tag-item.editing {
  cursor: move;
}

.filter-tag-item.dragging {
  opacity: 0.5;
}

.filter-tag-item.drag-over {
  padding-left: 20px;
}

.filter-tag-item:hover {
  transform: scale(1.02);
}

.drag-handle {
  display: flex;
  align-items: center;
  color: rgba(var(--color-teal-rgb), 0.6);
  cursor: move;
  padding: 2px;
}

.drag-handle:hover {
  color: #77969A;
}

.filter-tag-input {
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  border: 2px solid #44465b;
  border-radius: 12px;
  outline: none;
  min-width: 100px;
  transition: all 0.2s;
}

.filter-tag-btn {
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  border: none;
  border-radius: 0;
  cursor: pointer;
  transition: all 0.2s;
}

.filter-tag-btn:disabled {
  cursor: default;
  opacity: 0.8;
}

.filter-tag-btn:hover:not(.active):not(:disabled) {
  transform: translateY(-2px);
}

.filter-tag-btn.active {
  font-weight: 600;
  border-bottom: 2px solid #916a2d;
}

.filter-tag-btn.active:hover:not(:disabled) {
  transform: translateY(-2px);
}

.tag-color-picker-wrapper {
  display: flex;
  align-items: center;
}

.btn-color-picker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: rgba(var(--color-primary-rgb), 0.1);
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 4px;
  color: var(--color-primary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-color-picker:hover {
  background: rgba(var(--color-primary-rgb), 0.2);
}

.filter-header-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.btn-edit-filter,
.btn-save-filter,
.btn-clear-filter {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-edit-filter {
  background: rgba(var(--color-teal-rgb), 0.1);
  border-color: rgba(var(--color-teal-rgb), 0.3);
  color: #77969a;
}

.btn-edit-filter:hover {
  background: rgba(var(--color-teal-rgb), 0.2);
}

.btn-save-filter {
  background: rgba(var(--color-success-rgb), 0.15);
  border-color: rgba(var(--color-success-rgb), 0.3);
  color: #059669;
  font-size: 16px;
  font-weight: 600;
}

.btn-save-filter:hover {
  background: rgba(var(--color-success-rgb), 0.25);
}

.btn-clear-filter {
  background: rgba(var(--color-primary-rgb), 0.1);
  border-color: rgba(var(--color-primary-rgb), 0.3);
  color: var(--color-primary);
}

.btn-clear-filter:hover {
  background: rgba(var(--color-primary-rgb), 0.2);
}
</style>
