<template>
  <div v-if="allTags.length > 0" class="filter-section">

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
          :size="computeInputSize(editingTagText)"
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

        <!-- 編輯模式：編輯中的 tag 顯示顏色選擇器；其他 tag 顯示垃圾桶 -->
        <div v-if="isEditing" class="tag-color-picker-wrapper">
          <button
            v-if="editingTag === tag"
            :ref="el => setColorPickerButtonRef(tag, el)"
            class="btn-color-picker"
            :title="$t('taskList.setTagColor', { tag })"
            :style="{ backgroundColor: getTagColor(tag) }"
            @mousedown.prevent
            @click="handleToggleColorPicker(tag)"
          ></button>
          <button
            v-else
            class="btn-delete-tag"
            :title="$t('taskList.deleteTag', { tag })"
            @click="handleDeleteTag(tag)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              <line x1="10" y1="11" x2="10" y2="17"></line>
              <line x1="14" y1="11" x2="14" y2="17"></line>
            </svg>
          </button>
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
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </button>

        <!-- 清除篩選按鈕 -->
        <button
          v-if="selectedTags.length > 0 && !isEditing"
          class="btn-clear-filter"
          @click="clearFilter"
          :title="$t('taskList.clearFilter')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
          </svg>
        </button>
      </div>
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
const { getTagColor, updateTagColorLocal, saveTagColor, renameTag, deleteTag, saveTagOrder, getTagIds, tagsData, fetchTagColors } = useTaskTags($t)

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

// 記錄編輯過程中更改的顏色（tag -> color）
const pendingColorChanges = ref({})

// Computed
const displayedTagsList = computed(() => {
  if (props.isEditing && editingTagOrder.value.length > 0) {
    return editingTagOrder.value
  }

  // 非編輯模式下，按 customTagOrder 排序
  if (props.customTagOrder.length > 0 && props.allTags.length > 0) {
    const orderedTags = props.customTagOrder.filter(tag => props.allTags.includes(tag))
    const newTags = props.allTags.filter(tag => !props.customTagOrder.includes(tag))
    return [...orderedTags, ...newTags]
  }

  return props.allTags
})

const currentColor = computed(() => {
  if (colorPickerTag.value) {
    return getTagColor(colorPickerTag.value)
  }
  return 'var(--color-purple)'
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
  // 清空待保存的顏色更改
  pendingColorChanges.value = {}
}

async function saveEditing() {
  // 三段分開 catch，讓錯誤訊息對得上實際失敗的步驟
  const errors = []

  // 步驟 1：補建缺少的標籤
  try {
    const existingTagNames = new Set(tagsData.value.map(t => t.name))
    const missingTags = editingTagOrder.value.filter(tag => !existingTagNames.has(tag))

    if (missingTags.length > 0) {
      console.log('🏷️ 發現缺少的標籤，正在創建:', missingTags)
      for (const tagName of missingTags) {
        await saveTagColor(tagName, getTagColor(tagName))
      }
      await fetchTagColors()
    }
  } catch (error) {
    console.error('❌ 建立標籤失敗:', error)
    errors.push({ step: 'create', error })
  }

  // 步驟 2：保存順序
  try {
    const tagIds = getTagIds(editingTagOrder.value)
    console.log('🔍 保存順序 - 標籤名稱:', editingTagOrder.value)
    console.log('🔍 保存順序 - 標籤 ID:', tagIds)

    if (tagIds.length > 0) {
      await saveTagOrder(tagIds)
    } else {
      console.warn('⚠️ 沒有有效的標籤 ID 可保存')
    }
  } catch (error) {
    console.error('❌ 保存標籤順序失敗:', error)
    errors.push({ step: 'order', error })
  }

  // 步驟 3：保存待儲存的顏色
  try {
    const colorChangePromises = Object.entries(pendingColorChanges.value).map(
      ([tag, color]) => saveTagColor(tag, color)
    )
    if (colorChangePromises.length > 0) {
      await Promise.all(colorChangePromises)
      console.log('✅ 已保存', colorChangePromises.length, '個標籤顏色')
    }
  } catch (error) {
    console.error('❌ 保存標籤顏色失敗:', error)
    errors.push({ step: 'color', error })
  }

  if (errors.length > 0) {
    const stepLabels = { create: '建立標籤', order: '保存順序', color: '保存顏色' }
    const failedSteps = errors.map(e => stepLabels[e.step]).join('、')
    const firstMessage = errors[0].error?.message || String(errors[0].error)
    alert(`部分標籤編輯操作失敗（${failedSteps}）：${firstMessage}`)
  } else {
    emit('update:customTagOrder', [...editingTagOrder.value])
    emit('tags-reordered')
  }

  pendingColorChanges.value = {}
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

// 計算 input size：CJK 字元佔約 2 倍寬，加 3 字 buffer，上限 30 英文字寬
function computeInputSize(text) {
  const cjkMatches = text.match(/[　-〿぀-ゟ゠-ヿ一-鿿＀-￯]/g)
  const cjkCount = cjkMatches ? cjkMatches.length : 0
  const effective = text.length + cjkCount + 3
  return Math.min(Math.max(effective, 5), 30)
}

// 刪除標籤
async function handleDeleteTag(tag) {
  if (!confirm($t('taskList.deleteTagConfirm', { tag }))) {
    return
  }

  try {
    await deleteTag(tag)
  } catch (error) {
    alert($t('taskList.errorDeleteTagFull', { message: error.response?.data?.detail || error.message }))
    return
  }

  // 清除該 tag 在前端各 state 的痕跡（保留其他 tag 的暫存變更）
  if (editingTagOrder.value.includes(tag)) {
    editingTagOrder.value = editingTagOrder.value.filter(t => t !== tag)
  }
  if (props.selectedTags.includes(tag)) {
    emit('update:selectedTags', props.selectedTags.filter(t => t !== tag))
  }
  if (tag in pendingColorChanges.value) {
    const next = { ...pendingColorChanges.value }
    delete next[tag]
    pendingColorChanges.value = next
  }

  console.log('✅ ' + $t('taskList.successDeleteTag', { tag }))
  emit('refresh')
}

function handleColorSelected({ tag, color }) {
  // 只更新本地狀態，不立即保存到後端
  updateTagColorLocal(tag, color)

  // 記錄顏色更改，等保存時一起保存
  pendingColorChanges.value = { ...pendingColorChanges.value, [tag]: color }

  emit('tag-color-changed', { tag, color })
}
</script>

<style scoped>
/* 篩選列樣式 */
.filter-section {
  background: transparent;
  border-radius: 12px;
  padding: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
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
  color: var(--color-teal);
}

.filter-tag-input {
  padding: 6px 10px;
  font-size: 13px;
  font-weight: 500;
  border: 2px solid var(--color-secondary);
  border-radius: 12px;
  outline: none;
  min-width: 40px;
  width: auto;
  transition: all 0.2s;
}

.filter-tag-btn {
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  background: transparent;
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
  border-bottom: 2px solid var(--color-nav-recent-bg);
}

.filter-tag-btn.active:hover:not(:disabled) {
  transform: translateY(-2px);
}

.filter-tag-item.editing .filter-tag-btn {
  padding: 6px 2px;
}

.tag-color-picker-wrapper {
  display: flex;
  align-items: center;
}

.btn-color-picker {
  width: 16px;
  height: 16px;
  padding: 0;
  border: 1px solid rgba(0, 0, 0, 0.2);
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-color-picker:hover {
  transform: scale(1.15);
}

.btn-delete-tag {
  width: 20px;
  height: 20px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(var(--color-danger-rgb), 0.7);
  transition: all 0.2s;
}

.btn-delete-tag:hover {
  background: rgba(var(--color-danger-rgb), 0.12);
  color: var(--color-danger);
  transform: scale(1.1);
}

.btn-delete-tag svg {
  width: 14px;
  height: 14px;
}

.filter-header-actions {
  display: flex;
  gap: 8px;
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
  color: var(--color-teal);
}

.btn-edit-filter:hover {
  background: rgba(var(--color-teal-rgb), 0.2);
}

.btn-save-filter {
  background: rgba(var(--color-success-rgb), 0.15);
  border-color: rgba(var(--color-success-rgb), 0.3);
  color: var(--color-success-light);
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

/* === 響應式設計 === */

/* 平板以下 */
@media (max-width: 768px) {
  .filter-section {
    padding: 10px 12px;
    gap: 8px;
  }

  .filter-tags {
    gap: 4px;
  }

  .filter-tag-btn {
    padding: 4px 10px;
    font-size: var(--font-size-sm);
  }

  .filter-tag-input {
    padding: 4px 8px;
    font-size: var(--font-size-sm);
    min-width: 36px;
  }

  .drag-handle svg {
    width: 14px;
    height: 14px;
  }

  .btn-color-picker {
    width: 14px;
    height: 14px;
  }

  .btn-delete-tag {
    width: 18px;
    height: 18px;
  }

  .btn-delete-tag svg {
    width: 12px;
    height: 12px;
  }

  .filter-header-actions {
    gap: 6px;
  }

  .btn-edit-filter,
  .btn-save-filter,
  .btn-clear-filter {
    width: 26px;
    height: 26px;
  }

  .btn-edit-filter svg,
  .btn-save-filter svg,
  .btn-clear-filter svg {
    width: 12px;
    height: 12px;
  }
}

/* 小手機 */
@media (max-width: 480px) {
  .filter-section {
    padding: 8px;
    gap: 6px;
  }

  .filter-tags {
    gap: 2px;
  }

  .filter-tag-item {
    gap: 2px;
  }

  .filter-tag-btn {
    padding: 3px 8px;
    font-size: var(--font-size-sm);
  }

  .filter-tag-btn.active {
    border-bottom-width: 1.5px;
  }

  .filter-tag-input {
    padding: 3px 6px;
    font-size: var(--font-size-sm);
    min-width: 30px;
    border-width: 1.5px;
  }

  .filter-tag-item.editing .filter-tag-btn {
    padding: 3px 2px;
  }

  .drag-handle {
    padding: 1px;
  }

  .drag-handle svg {
    width: 12px;
    height: 12px;
  }

  .btn-color-picker {
    width: 12px;
    height: 12px;
  }

  .btn-delete-tag {
    width: 16px;
    height: 16px;
  }

  .btn-delete-tag svg {
    width: 10px;
    height: 10px;
  }

  .filter-header-actions {
    gap: 4px;
  }

  .btn-edit-filter,
  .btn-save-filter,
  .btn-clear-filter {
    width: 24px;
    height: 24px;
  }

  .btn-edit-filter svg,
  .btn-save-filter svg,
  .btn-clear-filter svg {
    width: 10px;
    height: 10px;
  }
}
</style>
