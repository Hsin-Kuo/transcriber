<template>
  <BottomSheet v-model="isOpen" :title="$t('taskList.tagPicker.title')">
    <div class="tag-picker">
      <input
        ref="searchInputEl"
        type="text"
        v-model="searchText"
        class="tag-picker-search"
        :placeholder="$t('taskList.tagPicker.searchOrCreate')"
        @keydown.enter="onEnter"
      />

      <div class="tag-picker-list">
        <button
          v-for="tag in filteredTags"
          :key="tag"
          type="button"
          class="tag-picker-row"
          @click="toggleTag(tag)"
        >
          <span class="tag-dot" :style="{ backgroundColor: getTagColor(tag) }"></span>
          <span class="tag-name">{{ tag }}</span>
          <span v-if="isAssigned(tag)" class="tag-check">✓</span>
        </button>

        <button
          v-if="showCreateRow"
          type="button"
          class="tag-picker-row tag-picker-create"
          @click="createAndAssign"
        >
          <span class="tag-create-icon">＋</span>
          <span class="tag-name">{{ $t('taskList.tagPicker.create', { name: trimmedSearch }) }}</span>
        </button>

        <p v-if="filteredTags.length === 0 && !showCreateRow" class="tag-picker-empty">
          {{ $t('taskList.tagPicker.noTags') }}
        </p>
      </div>
    </div>
  </BottomSheet>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import BottomSheet from '../common/BottomSheet.vue'
import { useTaskTags } from '../../composables/task/useTaskTags'

const { t: $t } = useI18n()
const { getTagColor } = useTaskTags($t)

const props = defineProps({
  modelValue: {
    type: Boolean,
    required: true
  },
  taskId: {
    type: String,
    required: true
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

const emit = defineEmits(['update:modelValue', 'tags-updated'])

const searchText = ref('')
const searchInputEl = ref(null)

const isOpen = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const trimmedSearch = computed(() => searchText.value.trim())

const filteredTags = computed(() => {
  if (!trimmedSearch.value) return props.allTags
  const needle = trimmedSearch.value.toLowerCase()
  return props.allTags.filter(tag => tag.toLowerCase().includes(needle))
})

// 有輸入值、且沒有完全符合（大小寫不敏感）的既有標籤時，顯示「建立」列
const showCreateRow = computed(() => {
  if (!trimmedSearch.value) return false
  const needle = trimmedSearch.value.toLowerCase()
  return !props.allTags.some(tag => tag.toLowerCase() === needle)
})

function isAssigned(tag) {
  return props.tags.includes(tag)
}

function emitTags(newTags) {
  emit('tags-updated', { taskId: props.taskId, tags: newTags })
}

function toggleTag(tag) {
  const current = props.tags || []
  const next = current.includes(tag)
    ? current.filter(t => t !== tag)
    : [...current, tag]
  emitTags(next)
}

function createAndAssign() {
  const name = trimmedSearch.value
  if (!name) return
  const current = props.tags || []
  if (!current.includes(name)) {
    emitTags([...current, name])
  }
  searchText.value = ''
}

function onEnter() {
  if (showCreateRow.value) {
    createAndAssign()
  }
}

watch(isOpen, (val) => {
  if (val) {
    searchText.value = ''
    nextTick(() => searchInputEl.value?.focus())
  }
})
</script>

<style scoped>
.tag-picker {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tag-picker-search {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 14px;
  font-size: 15px;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 10px;
  background: var(--color-bg, white);
  color: var(--main-text);
}

.tag-picker-search:focus {
  outline: none;
  border-color: rgba(var(--color-primary-rgb), 0.6);
}

.tag-picker-list {
  display: flex;
  flex-direction: column;
}

.tag-picker-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-height: 44px;
  padding: 0 4px;
  background: transparent;
  border: none;
  border-bottom: 1px solid rgba(var(--color-divider-rgb), 0.2);
  font-size: 15px;
  color: var(--main-text);
  cursor: pointer;
  text-align: left;
}

.tag-picker-row:last-child {
  border-bottom: none;
}

.tag-picker-row:active {
  background: rgba(var(--color-divider-rgb), 0.08);
}

.tag-dot {
  flex-shrink: 0;
  width: 14px;
  height: 14px;
  border-radius: 50%;
}

.tag-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-check {
  flex-shrink: 0;
  color: var(--color-success, #10b981);
  font-weight: 700;
}

.tag-picker-create {
  color: var(--color-primary);
  font-weight: 500;
}

.tag-create-icon {
  flex-shrink: 0;
  width: 14px;
  text-align: center;
  font-weight: 700;
}

.tag-picker-empty {
  padding: 16px 4px;
  text-align: center;
  font-size: 13px;
  color: var(--color-text-muted);
}
</style>
