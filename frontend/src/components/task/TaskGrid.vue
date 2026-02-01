<template>
  <div>
    <!-- 空狀態 -->
    <div v-if="tasks.length === 0" class="empty-state">
      <p>{{ $t('taskList.noTranscriptionTasks') }}</p>
    </div>

    <!-- 任務列表 -->
    <div v-else class="tasks" :class="{ 'batch-mode': isBatchMode }">
      <TaskCard
        v-for="task in tasks"
        :key="task.task_id"
        :task="task"
        :is-batch-mode="isBatchMode"
        :is-selected="selectedTaskIds.has(task.task_id)"
        :is-newest="isNewestTask(task)"
        :keep-audio-count="keepAudioCount"
        :all-tags="allTags"
        @view="(taskId) => emit('view', taskId)"
        @download="(task) => emit('download', task)"
        @delete="(taskId) => emit('delete', taskId)"
        @cancel="(taskId) => emit('cancel', taskId)"
        @toggle-selection="(taskId) => emit('toggle-selection', taskId)"
        @toggle-keep-audio="(task) => emit('toggle-keep-audio', task)"
        @tags-updated="(data) => emit('tags-updated', data)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import TaskCard from './TaskCard.vue'

const { t: $t } = useI18n()

// Props
const props = defineProps({
  tasks: {
    type: Array,
    required: true
  },
  isBatchMode: {
    type: Boolean,
    default: false
  },
  selectedTaskIds: {
    type: Set,
    default: () => new Set()
  },
  allTasks: {
    type: Array,
    default: () => []
  },
  allTags: {
    type: Array,
    default: () => []
  }
})

// Emits
const emit = defineEmits([
  'view',
  'download',
  'delete',
  'cancel',
  'toggle-selection',
  'toggle-keep-audio',
  'tags-updated'
])

// Computed
const keepAudioCount = computed(() => {
  return props.allTasks.filter(t =>
    t.status === 'completed' &&
    t.audio_file &&
    t.keep_audio
  ).length
})

// Methods
function isNewestTask(task) {
  const completedTasks = props.allTasks.filter(t =>
    t.status === 'completed' &&
    t.audio_file
  )

  if (completedTasks.length === 0) return false

  // 按完成時間排序，取最新的
  const sorted = [...completedTasks].sort((a, b) =>
    (b.completed_at || '').localeCompare(a.completed_at || '')
  )

  return sorted[0]?.task_id === task.task_id
}
</script>

<style scoped>
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  font-size: 13px;
}

.empty-state p:first-child {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 8px;
  color: rgba(var(--color-text-dark-rgb), 0.7);
}

.tasks {
  display: flex;
  flex-direction: column;
  gap: 0px;
}

.tasks :deep(.task-wrapper:last-child) {
  margin-bottom: 0;
}

/* 批次編輯模式下的任務列表 - 保持堆疊效果 */
.tasks.batch-mode {
  gap: 0;
  box-shadow: 0 2px 8px rgba(var(--color-primary-rgb), 0.08);
  background: var(--color-nav-recent-bg);
  padding: 20px;
  border-radius: 12px;
}

.tasks.batch-mode :deep(.task-wrapper) {
  /* 保持卡片重疊效果 */
  margin-bottom: -34px;
  padding: 0;
  border-radius: 0;
  background: transparent;
}

.tasks.batch-mode :deep(.task-wrapper:last-child) {
  margin-bottom: 0;
}

.tasks.batch-mode :deep(.task-wrapper:not(:last-child) .task-item) {
  border-bottom: 1px solid rgba(var(--color-primary-rgb), 0.1);
}

.tasks.batch-mode :deep(.task-wrapper:hover .task-item) {
  box-shadow: none;
  transform: none;
  filter: none;
}

/* === 響應式設計 === */

/* 平板以下 */
@media (max-width: 768px) {
  .empty-state {
    padding: 40px 16px;
    font-size: 12px;
  }

  .empty-state p:first-child {
    font-size: 13px;
  }

  .tasks.batch-mode {
    padding: 12px;
    border-radius: 10px;
  }

  .tasks.batch-mode :deep(.task-wrapper) {
    margin-bottom: -28px;
  }
}

/* 小手機 */
@media (max-width: 480px) {
  .empty-state {
    padding: 32px 12px;
  }

  .tasks.batch-mode {
    padding: 8px;
    border-radius: 8px;
  }

  .tasks.batch-mode :deep(.task-wrapper) {
    margin-bottom: -24px;
  }
}
</style>
