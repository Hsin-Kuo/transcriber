<template>
  <div class="file-order-list">
    <div class="list-header">
      <h4>已選擇 {{ files.length }} 個檔案</h4>
      <span class="hint">拖動調整順序</span>
    </div>

    <draggable
      :list="fileList"
      @change="handleDragEnd"
      @end="handleDragEnd"
      class="file-items"
      handle=".drag-handle"
    >
      <div
        v-for="(element, index) in fileList"
        :key="element.id"
        class="file-item"
      >
        <div class="drag-handle">⋮⋮</div>
        <div class="file-number">{{ index + 1 }}</div>
        <div class="file-info">
          <span class="file-name">{{ element.name }}</span>
          <span class="file-size">{{ formatSize(element.size) }}</span>
        </div>
        <button class="remove-btn" @click="removeFile(index)" title="移除">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
    </draggable>

    <div class="total-info">
      <span>合併後總大小：{{ totalSize }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { VueDraggableNext as draggable } from 'vue-draggable-next'

const props = defineProps({
  files: {
    type: Array,
    required: true
  }
})

const emit = defineEmits(['order-changed', 'file-removed'])

// 追蹤是否正在從 props 同步（避免循環更新）
let isSyncingFromProps = false

// 為每個檔案添加唯一 ID（用於 draggable）
// 注意：File 物件無法直接展開，需要保留原始 File 並添加額外屬性
function wrapFiles(files) {
  return files.map((f, i) => ({
    file: f,           // 保留原始 File 物件
    name: f.name,
    size: f.size,
    type: f.type,
    id: `file-${i}-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
  }))
}

const fileList = ref(wrapFiles(props.files))

// 監聽 props.files 變化（僅在檔案數量改變時同步）
watch(() => props.files.length, () => {
  isSyncingFromProps = true
  fileList.value = wrapFiles(props.files)
  isSyncingFromProps = false
})

// 監聽 fileList 變化，自動 emit 新順序
watch(fileList, (newList) => {
  if (!isSyncingFromProps && newList.length > 0) {
    // 返回原始 File 物件（按新順序）
    emit('order-changed', newList.map(item => item.file))
  }
}, { deep: true })

function handleDragEnd() {
  // 拖曳結束時確保順序已更新（備用觸發）
  const orderedFiles = fileList.value.map(item => item.file)
  console.log('📋 FileOrderList 順序更新:', orderedFiles.map((f, i) => `${i+1}. ${f.name}`))
  emit('order-changed', orderedFiles)
}

function removeFile(index) {
  emit('file-removed', index)
}

const totalSize = computed(() => {
  const bytes = fileList.value.reduce((sum, f) => sum + f.size, 0)
  return formatSize(bytes)
})

function formatSize(bytes) {
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}
</script>

<style scoped>
.file-order-list {
  width: 100%;
  max-width: 700px;
  margin: 20px auto;
  padding: 20px;
  background: var(--main-bg);
  border-radius: 16px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid rgba(var(--color-primary-rgb), 0.2);
}

.list-header h4 {
  font-size: 16px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.9);
  margin: 0;
}

.list-header .hint {
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb), 0.5);
}

.file-items {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: var(--color-bg-light);
  border: 1px solid rgba(var(--color-primary-rgb), 0.2);
  border-radius: 10px;
  transition: all 0.2s;
  cursor: move;
}

.file-item:hover {
  background: var(--color-bg-lighter);
  border-color: rgba(var(--color-primary-rgb), 0.4);
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(var(--color-text-dark-rgb), 0.1);
}

.drag-handle {
  color: rgba(var(--color-text-dark-rgb), 0.4);
  font-size: 18px;
  cursor: grab;
  user-select: none;
}

.drag-handle:active {
  cursor: grabbing;
}

.file-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: rgba(var(--color-primary-rgb), 0.15);
  border-radius: 50%;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
}

.file-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.file-name {
  font-size: 14px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-size {
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb), 0.6);
}

.remove-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: color-mix(in srgb, var(--color-danger) 70%, transparent);
  cursor: pointer;
  transition: all 0.2s;
}

.remove-btn:hover {
  background: color-mix(in srgb, var(--color-danger) 10%, transparent);
  color: var(--color-danger);
}

.total-info {
  padding-top: 12px;
  border-top: 1px solid rgba(var(--color-primary-rgb), 0.2);
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.7);
}

@media (max-width: 768px) {
  .file-order-list {
    padding: 16px;
  }

  .file-item {
    padding: 10px;
  }

  .file-name {
    font-size: 13px;
  }
}
</style>
