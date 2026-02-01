<template>
  <div class="task-tags-section" @click.stop>
    <!-- 編輯模式 -->
    <div v-if="isEditing" class="tag-edit-mode">
      <div class="tag-edit-header">
        <span class="tag-edit-label">{{ $t('taskList.editTags') }}</span>
        <div class="tag-edit-actions">
          <button class="btn-tag-action btn-save" @click="handleSave" :title="$t('taskList.save')">
            ✓
          </button>
          <button class="btn-tag-action btn-cancel" @click="handleCancel" :title="$t('taskList.cancel')">
            ✕
          </button>
        </div>
      </div>

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
        <div class="available-tags-label">{{ $t('taskList.quickSelect') }}</div>
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
            + {{ tag }}
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
import { ref, computed, nextTick } from 'vue'
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
const emit = defineEmits(['tags-updated'])

// State
const isEditing = ref(false)
const editingTags = ref([])
const editingTagInput = ref('')
const editingTagIndex = ref(null)
const editingTagText = ref('')
const tagTextInput = ref(null)

// Computed
const availableTagsList = computed(() => {
  return props.allTags.filter(tag => !editingTags.value.includes(tag))
})

// Methods
function startEditing() {
  isEditing.value = true
  editingTags.value = props.tags ? [...props.tags] : []
  editingTagInput.value = ''
}

function addTag() {
  const tag = editingTagInput.value.trim()
  if (tag && !editingTags.value.includes(tag)) {
    editingTags.value.push(tag)
    editingTagInput.value = ''
  } else if (editingTags.value.includes(tag)) {
    editingTagInput.value = ''
  }
}

function quickAddTag(tag) {
  if (!editingTags.value.includes(tag)) {
    editingTags.value.push(tag)
  }
}

function removeTag(index) {
  editingTags.value.splice(index, 1)
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
    // 檢查新標籤是否已存在
    if (!editingTags.value.includes(newText)) {
      editingTags.value[index] = newText
    }
  }
  editingTagIndex.value = null
  editingTagText.value = ''
}

function cancelTagText() {
  editingTagIndex.value = null
  editingTagText.value = ''
}

function handleSave() {
  emit('tags-updated', {
    taskId: props.taskId,
    tags: [...editingTags.value]
  })
  isEditing.value = false
  editingTags.value = []
  editingTagInput.value = ''
  editingTagIndex.value = null
  editingTagText.value = ''
}

function handleCancel() {
  isEditing.value = false
  editingTags.value = []
  editingTagInput.value = ''
  editingTagIndex.value = null
  editingTagText.value = ''
}
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
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(var(--color-primary-rgb), 0.2);
  border-radius: 8px;
  padding: 12px;
}

.tag-edit-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.tag-edit-label {
  font-size: 12px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.7);
}

.tag-edit-actions {
  display: flex;
  gap: 6px;
}

.btn-tag-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-tag-action.btn-save {
  background: rgba(var(--color-success-rgb), 0.15);
  color: var(--color-success-light);
}

.btn-tag-action.btn-save:hover {
  background: rgba(var(--color-success-rgb), 0.25);
}

.btn-tag-action.btn-cancel {
  background: rgba(var(--color-danger-rgb), 0.15);
  color: var(--color-danger);
}

.btn-tag-action.btn-cancel:hover {
  background: rgba(var(--color-danger-rgb), 0.25);
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
  background: white;
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

.available-tags-label {
  font-size: 11px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
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
  border: 1.5px solid;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: white;
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
