<template>
  <div class="task-tags-section" ref="tagSectionEl" @click.stop>
    <!-- 編輯模式 -->
    <div v-if="isEditing" class="tag-edit-mode">

      <!-- 標籤輸入框 -->
      <div class="tag-input-wrapper-inline">
        <input
          type="text"
          v-model="editingTagInput"
          @keydown.enter.prevent="addTag"
          @keydown.comma.prevent="addTag"
          :placeholder="$t('taskList.tagInputPlaceholder')"
          class="tag-input-inline"
        />
        <button
          type="button"
          class="btn-add-tag-inline"
          @click="addTag"
          :disabled="!editingTagInput.trim()"
        >
          +
        </button>
      </div>

      <!-- 可快速選擇的現有標籤 -->
      <div v-if="availableTagsList.length > 0" class="available-tags-section">
        <div class="available-tags">
          <button
            v-for="tag in availableTagsList"
            :key="tag"
            type="button"
            class="available-tag-btn"
            :style="{
              backgroundColor: `${getTagColor(tag)}15`,
              borderColor: getTagColor(tag),
              color: getTagColor(tag)
            }"
            @click="quickAddTag(tag)"
            :title="$t('taskList.clickToAddTag', { tag })"
          >
            {{ tag }}
          </button>
        </div>
      </div>

      <!-- 已添加的標籤列表（可編輯） -->
      <div v-if="editingTags.length > 0" class="task-tags">
        <template v-for="(tag, index) in editingTags" :key="index">
          <!-- 編輯狀態：顯示輸入框 -->
          <span
            v-if="editingTagIndex === index"
            class="tag-badge-editing"
            :style="{ backgroundColor: getTagColor(tag) }"
          >
            <input
              type="text"
              class="tag-text-input"
              v-model="editingTagText"
              @keyup.enter="saveTagText(index)"
              @keyup.esc="cancelTagText"
              @blur="saveTagText(index)"
              ref="tagTextInput"
            />
            <button
              type="button"
              class="save-tag-text"
              @click="saveTagText(index)"
              :title="$t('taskList.save')"
            >
              ✓
            </button>
            <button
              type="button"
              class="cancel-tag-text"
              @click="cancelTagText"
              :title="$t('taskList.cancel')"
            >
              ✕
            </button>
          </span>

          <!-- 一般狀態：顯示標籤 -->
          <span
            v-else
            class="tag-badge editable"
            :style="{ backgroundColor: getTagColor(tag) }"
            @click="startEditingTagText(index, tag)"
            :title="$t('taskList.clickToEdit')"
          >
            {{ tag }}
            <button
              type="button"
              class="remove-tag-inline"
              @click.stop="removeTag(index)"
              :title="$t('taskList.remove')"
            >
              ×
            </button>
          </span>
        </template>
      </div>

    </div>

    <!-- 顯示模式 -->
    <div v-else class="task-tags-display">
      <div v-if="tags && tags.length > 0" class="task-tags">
        <span
          v-for="tag in tags"
          :key="tag"
          class="tag-badge"
          :style="{ backgroundColor: getTagColor(tag) }"
        >
          {{ tag }}
        </span>
        <button
          class="btn-edit-tags"
          @click="startEditing"
          :title="$t('taskList.editTags')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
          </svg>
        </button>
      </div>
      <button
        v-else
        class="btn-add-tags"
        @click="startEditing"
        :title="$t('taskList.addTag')"
      >
        {{ $t('taskList.addTagButton') }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTaskTags } from '../../composables/task/useTaskTags'

const { t: $t } = useI18n()
const { getTagColor } = useTaskTags($t)

// Props
const props = defineProps({
  taskId: {
    type: String,
    default: ''
  },
  tags: {
    type: Array,
    default: () => []
  },
  allTags: {
    type: Array,
    default: () => []
  }
})

// Emits
const emit = defineEmits(['tags-updated', 'editing-change'])

// State
const isEditing = ref(false)
const editingTags = ref([])
const editingTagInput = ref('')
const editingTagIndex = ref(null)
const editingTagText = ref('')
const tagTextInput = ref(null)
const tagSectionEl = ref(null)

// Computed
const availableTagsList = computed(() => {
  return props.allTags.filter(tag => !editingTags.value.includes(tag))
})

// 發送更新
function emitUpdate() {
  emit('tags-updated', {
    taskId: props.taskId,
    tags: [...editingTags.value]
  })
}

// 點擊外部關閉編輯
function handleClickOutside(event) {
  if (tagSectionEl.value && !tagSectionEl.value.contains(event.target)) {
    event.stopPropagation()
    event.preventDefault()
    closeEditing()
  }
}

// Methods
function startEditing() {
  isEditing.value = true
  emit('editing-change', true)
  editingTags.value = props.tags ? [...props.tags] : []
  editingTagInput.value = ''
  nextTick(() => {
    document.addEventListener('click', handleClickOutside, true)
  })
}

function closeEditing() {
  document.removeEventListener('click', handleClickOutside, true)
  isEditing.value = false
  emit('editing-change', false)
  editingTags.value = []
  editingTagInput.value = ''
  editingTagIndex.value = null
  editingTagText.value = ''
}

function addTag() {
  const tag = editingTagInput.value.trim()
  if (tag && !editingTags.value.includes(tag)) {
    editingTags.value.push(tag)
    editingTagInput.value = ''
    emitUpdate()
  } else if (editingTags.value.includes(tag)) {
    editingTagInput.value = ''
  }
}

function quickAddTag(tag) {
  if (!editingTags.value.includes(tag)) {
    editingTags.value.push(tag)
    emitUpdate()
  }
}

function removeTag(index) {
  editingTags.value.splice(index, 1)
  emitUpdate()
}

async function startEditingTagText(index, tag) {
  editingTagIndex.value = index
  editingTagText.value = tag

  // 等待 DOM 更新後自動聚焦輸入框
  await nextTick()
  if (tagTextInput.value) {
    const input = Array.isArray(tagTextInput.value) ? tagTextInput.value[0] : tagTextInput.value
    if (input) {
      input.focus()
      input.select()
    }
  }
}

function saveTagText(index) {
  const newText = editingTagText.value.trim()
  if (newText && newText !== editingTags.value[index]) {
    if (!editingTags.value.includes(newText)) {
      editingTags.value[index] = newText
      emitUpdate()
    }
  }
  editingTagIndex.value = null
  editingTagText.value = ''
}

function cancelTagText() {
  editingTagIndex.value = null
  editingTagText.value = ''
}

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside, true)
})
</script>

<style scoped>
/* 標籤區域 */
.task-tags-section {
  display: inline-flex;
  align-items: center;
}

.task-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.task-tags-display .task-tags {
  margin-top: 0;
}

/* 標籤徽章 */
.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  color: white;
  background: var(--color-purple);
  /* box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1); */
  transition: all 0.2s ease;
  cursor: default;
}

.tag-badge:hover {
  transform: translateY(-1px);
  /* box-shadow: 0 3px 8px rgba(0, 0, 0, 0.15); */
}

.tag-badge.editable {
  padding-right: 8px;
  cursor: pointer;
}

.tag-badge.editable:hover {
  opacity: 0.9;
  /* box-shadow: 0 3px 8px rgba(0, 0, 0, 0.2); */
}

/* 標籤文字編輯狀態 */
.tag-badge-editing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  color: white;
  background: var(--color-purple);
  /* box-shadow: 0 2px 8px rgba(var(--color-purple-rgb), 0.3); */
}

.tag-text-input {
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  width: 80px;
  color: var(--color-text-dark);
}

.tag-text-input:focus {
  outline: none;
  border-color: white;
}

.save-tag-text,
.cancel-tag-text {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  background: rgba(255, 255, 255, 0.3);
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.save-tag-text:hover {
  background: rgba(var(--color-success-rgb), 0.8);
}

.cancel-tag-text:hover {
  background: rgba(var(--color-danger-rgb), 0.8);
}

.remove-tag-inline {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  margin: 0;
  background: rgba(255, 255, 255, 0.3);
  border: none;
  border-radius: 50%;
  color: white;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-tag-inline:hover {
  background: rgba(var(--color-danger-rgb), 0.8);
}

/* 編輯標籤按鈕 */
.btn-edit-tags {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 6px;
  background: rgba(var(--color-teal-rgb), 0.1);
  border: 1px solid rgba(var(--color-teal-rgb), 0.3);
  border-radius: 4px;
  color: var(--color-teal);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 12px;
}

.btn-edit-tags:hover {
  background: rgba(var(--color-teal-rgb), 0.2);
  border-color: rgba(var(--color-teal-rgb), 0.5);
  transform: translateY(-1px);
}

/* 添加標籤按鈕 */
.btn-add-tags {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  background: rgba(246, 156, 92, 0.1);
  border: 1px dashed rgba(246, 141, 92, 0.3);
  border-radius: 4px;
  color: rgba(217, 108, 40, 0.9);
  cursor: pointer;
  transition: all 0.2s;
  font-size: 12px;
  font-weight: 500;
}

.btn-add-tags:hover {
  background: rgba(246, 156, 92, 0.15);
  border-color: rgba(246, 141, 92, 0.5);
  transform: translateY(-1px);
}

/* 編輯模式 */
.tag-edit-mode {
  background: var(--color-bg-light, rgba(255, 255, 255, 0.5));
  border: 1px solid rgba(var(--color-primary-rgb), 0.2);
  border-radius: 8px;
  padding: 12px;
}

/* 標籤輸入 */
.tag-input-wrapper-inline {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}

.tag-input-inline {
  flex: 1;
  padding: 6px 10px;
  font-size: 13px;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 6px;
  background: var(--color-bg, white);
  color: var(--main-text);
  transition: all 0.2s;
}

.tag-input-inline:focus {
  outline: none;
  border-color: rgba(var(--color-primary-rgb), 0.5);
}

.btn-add-tag-inline {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--color-purple-rgb), 0.15);
  border: 1px solid rgba(var(--color-purple-rgb), 0.3);
  border-radius: 6px;
  color: var(--color-purple);
  font-size: 18px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-add-tag-inline:hover:not(:disabled) {
  background: rgba(var(--color-purple-rgb), 0.25);
  border-color: rgba(var(--color-purple-rgb), 0.5);
}

.btn-add-tag-inline:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 快速選擇區域 */
.available-tags-section {
  margin-bottom: 12px;
  padding: 10px;
  background: rgba(var(--color-teal-rgb), 0.05);
  border: 1px dashed rgba(var(--color-teal-rgb), 0.2);
  border-radius: 6px;
}

.available-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.available-tag-btn {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border: 1.5px dashed;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--color-bg, white);
}

.available-tag-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
  opacity: 0.9;
}

/* 響應式：手機版隱藏編輯按鈕 */
@media (max-width: 768px) {
  .btn-edit-tags,
  .btn-add-tags {
    display: none;
  }
}
</style>
