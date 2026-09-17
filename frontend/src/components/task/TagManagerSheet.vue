<template>
  <BottomSheet
    v-model="isOpen"
    :title="mode === 'list' ? $t('taskList.tagManager.title') : $t('taskList.tagManager.editTitle')"
  >
    <!-- 清單模式 -->
    <div v-if="mode === 'list'" class="tm-list" ref="listEl">
      <div
        v-for="(tag, index) in localOrder"
        :key="tag"
        class="tm-row"
        :class="{ dragging: dragIndex === index }"
      >
        <span
          class="tm-handle"
          @pointerdown="onHandlePointerDown(index, $event)"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="8" y1="6" x2="21" y2="6"></line>
            <line x1="8" y1="12" x2="21" y2="12"></line>
            <line x1="8" y1="18" x2="21" y2="18"></line>
            <line x1="3" y1="6" x2="3.01" y2="6"></line>
            <line x1="3" y1="12" x2="3.01" y2="12"></line>
            <line x1="3" y1="18" x2="3.01" y2="18"></line>
          </svg>
        </span>
        <span class="tm-dot" :style="{ backgroundColor: getTagColor(tag) }"></span>
        <button type="button" class="tm-name-btn" @click="openEdit(tag)">
          <span class="tm-name">{{ tag }}</span>
          <span class="tm-chevron">›</span>
        </button>
      </div>

      <p v-if="localOrder.length === 0" class="tm-empty">{{ $t('taskList.tagManager.empty') }}</p>
    </div>

    <!-- 編輯模式 -->
    <div v-else class="tm-edit">
      <button type="button" class="tm-back" @click="backToList">
        ‹ {{ $t('taskList.tagManager.back') }}
      </button>

      <label class="tm-field-label">{{ $t('taskList.tagManager.name') }}</label>
      <input
        type="text"
        class="tm-name-input"
        v-model="editingName"
        @blur="commitRename"
        @keyup.enter="commitRename"
      />

      <label class="tm-field-label">{{ $t('taskList.tagManager.color') }}</label>
      <div class="tm-color-grid">
        <button
          v-for="color in presetColors"
          :key="color"
          type="button"
          class="tm-color-swatch"
          :class="{ active: getTagColor(editingTag) === color }"
          :style="{ backgroundColor: color }"
          @click="selectColor(color)"
        ></button>
      </div>

      <button
        type="button"
        class="tm-delete-btn"
        :class="{ confirming: confirmingDelete }"
        @click="handleDeleteClick"
      >
        {{ confirmingDelete ? $t('taskList.tagManager.confirmDelete') : $t('taskList.tagManager.delete') }}
      </button>
    </div>
  </BottomSheet>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BottomSheet from '../common/BottomSheet.vue'
import { useTaskTags } from '../../composables/task/useTaskTags'

const { t: $t } = useI18n()
const {
  getTagColor,
  updateTagColorLocal,
  saveTagColor,
  renameTag,
  deleteTag,
  saveTagOrder,
  getTagIds,
  presetColors
} = useTaskTags($t)

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true
  },
  tags: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue', 'refresh'])

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const mode = ref('list')
const localOrder = ref([])
const listEl = ref(null)
const dragIndex = ref(null)

const editingTag = ref(null)
const editingName = ref('')
const confirmingDelete = ref(false)

watch(isOpen, (val) => {
  if (val) {
    mode.value = 'list'
    localOrder.value = [...props.tags]
  }
})

function openEdit(tag) {
  editingTag.value = tag
  editingName.value = tag
  confirmingDelete.value = false
  mode.value = 'edit'
}

function backToList() {
  mode.value = 'list'
  editingTag.value = null
  confirmingDelete.value = false
}

// ===== 拖曳排序（Pointer Events） =====
function onHandlePointerDown(index, event) {
  dragIndex.value = index
  try {
    event.target.setPointerCapture(event.pointerId)
  } catch { /* no-op：部分瀏覽器對非目標元素 capture 會丟例外，忽略即可 */ }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onPointerMove(event) {
  if (dragIndex.value === null || !listEl.value) return
  const rows = Array.from(listEl.value.querySelectorAll('.tm-row'))
  if (rows.length === 0) return

  const y = event.clientY
  let targetIndex = rows.length - 1
  for (let i = 0; i < rows.length; i++) {
    const rect = rows[i].getBoundingClientRect()
    const mid = rect.top + rect.height / 2
    if (y < mid) {
      targetIndex = i
      break
    }
  }

  if (targetIndex !== dragIndex.value) {
    const arr = [...localOrder.value]
    const [item] = arr.splice(dragIndex.value, 1)
    arr.splice(targetIndex, 0, item)
    localOrder.value = arr
    dragIndex.value = targetIndex
  }
}

async function onPointerUp() {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  dragIndex.value = null
  await persistOrder()
}

async function persistOrder() {
  const ids = getTagIds(localOrder.value)
  if (ids.length === 0) return
  try {
    await saveTagOrder(ids)
    emit('refresh')
  } catch (error) {
    alert($t('taskList.errorSaveTagOrderFull', { message: error.response?.data?.detail || error.message }))
  }
}

// ===== 改名 =====
async function commitRename() {
  const oldTag = editingTag.value
  const newTag = editingName.value.trim()

  if (!newTag || newTag === oldTag) {
    editingName.value = oldTag
    return
  }

  if (localOrder.value.some(t => t !== oldTag && t === newTag)) {
    alert($t('taskList.errorTagExists', { tag: newTag }))
    editingName.value = oldTag
    return
  }

  try {
    await renameTag(oldTag, newTag, [])
    const idx = localOrder.value.indexOf(oldTag)
    if (idx !== -1) {
      const arr = [...localOrder.value]
      arr[idx] = newTag
      localOrder.value = arr
    }
    editingTag.value = newTag
    emit('refresh')
  } catch (error) {
    alert($t('taskList.errorRenameTagFull', { message: error.message }))
    editingName.value = oldTag
  }
}

// ===== 改色 =====
async function selectColor(color) {
  if (!editingTag.value) return
  updateTagColorLocal(editingTag.value, color)
  try {
    await saveTagColor(editingTag.value, color)
  } catch (error) {
    alert($t('taskList.errorUpdateTagColorFull', { message: error.message }))
  }
}

// ===== 刪除（二段確認） =====
async function handleDeleteClick() {
  if (!confirmingDelete.value) {
    confirmingDelete.value = true
    return
  }

  const tag = editingTag.value
  try {
    await deleteTag(tag)
    localOrder.value = localOrder.value.filter(t => t !== tag)
    emit('refresh')
    backToList()
  } catch (error) {
    alert($t('taskList.errorDeleteTagFull', { message: error.response?.data?.detail || error.message }))
    confirmingDelete.value = false
  }
}
</script>

<style scoped>
.tm-list {
  display: flex;
  flex-direction: column;
}

.tm-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  border-bottom: 1px solid rgba(var(--color-divider-rgb), 0.2);
}

.tm-row:last-child {
  border-bottom: none;
}

.tm-row.dragging {
  opacity: 0.5;
  background: rgba(var(--color-divider-rgb), 0.08);
}

.tm-handle {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 44px;
  color: rgba(var(--color-teal-rgb), 0.7);
  cursor: grab;
  touch-action: none;
}

.tm-dot {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  border-radius: 50%;
}

.tm-name-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
  padding: 0 4px;
  background: transparent;
  border: none;
  font-size: 15px;
  color: var(--main-text);
  cursor: pointer;
  text-align: left;
}

.tm-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tm-chevron {
  flex-shrink: 0;
  color: var(--color-text-muted);
  font-size: 18px;
}

.tm-empty {
  padding: 24px 4px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted);
}

/* 編輯模式 */
.tm-edit {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tm-back {
  align-self: flex-start;
  padding: 6px 4px;
  margin-bottom: 4px;
  background: transparent;
  border: none;
  font-size: 14px;
  color: var(--color-teal);
  cursor: pointer;
}

.tm-field-label {
  margin-top: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-muted);
}

.tm-name-input {
  width: 100%;
  box-sizing: border-box;
  min-height: 44px;
  padding: 10px 12px;
  font-size: 15px;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  background: var(--color-bg, white);
  color: var(--main-text);
}

.tm-name-input:focus {
  outline: none;
  border-color: rgba(var(--color-primary-rgb), 0.6);
}

.tm-color-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
}

.tm-color-swatch {
  width: 100%;
  aspect-ratio: 1;
  min-width: 32px;
  min-height: 32px;
  border: 2px solid rgba(255, 255, 255, 0.8);
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.tm-color-swatch.active {
  border-color: var(--main-text);
  box-shadow: 0 0 0 2px var(--color-primary);
}

.tm-delete-btn {
  margin-top: 20px;
  min-height: 44px;
  padding: 10px;
  background: rgba(var(--color-danger-rgb), 0.1);
  border: 1px solid rgba(var(--color-danger-rgb), 0.3);
  border-radius: 8px;
  color: var(--color-danger);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.tm-delete-btn.confirming {
  background: var(--color-danger);
  border-color: var(--color-danger);
  color: white;
}
</style>
