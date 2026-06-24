<template>
  <div>
    <!-- 空狀態 -->
    <div v-if="tasks.length === 0" class="empty-state">
      <!-- 完全沒有任務（新使用者）：引導 + CTA -->
      <template v-if="isFirstTime">
        <svg class="empty-illustration" viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M32 40V14" />
          <path d="M23 23l9-9 9 9" />
          <path d="M14 40v6a4 4 0 0 0 4 4h28a4 4 0 0 0 4-4v-6" />
        </svg>
        <h3>{{ $t('taskList.empty.title') }}</h3>
        <p class="empty-subtitle">{{ $t('taskList.empty.subtitle') }}</p>
        <router-link to="/" class="empty-cta">{{ $t('taskList.empty.cta') }}</router-link>
      </template>
      <!-- 有任務、但目前篩選/分類為空：維持單行提示 -->
      <p v-else>{{ $t('taskList.noTranscriptionTasks') }}</p>
    </div>

    <!-- 任務列表 -->
    <div v-else class="tasks" :class="{ 'batch-mode': isBatchMode }">
      <slot name="before-cards"></slot>
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
// 區分「完全沒任務的新使用者」與「篩選後為空」：只有前者顯示引導 + CTA
const isFirstTime = computed(() => props.allTasks.length === 0)

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

.empty-illustration {
  width: 56px;
  height: 56px;
  margin: 0 auto 18px;
  color: rgba(var(--color-text-dark-rgb), 0.35);
  display: block;
}

.empty-state h3 {
  font-size: 17px;
  font-weight: 700;
  margin-bottom: 10px;
  color: rgba(var(--color-text-dark-rgb), 0.85);
}

.empty-subtitle {
  max-width: 420px;
  margin: 0 auto 22px;
  font-size: 13px;
  line-height: 1.7;
  color: rgba(var(--color-text-dark-rgb), 0.6);
}

.empty-cta {
  display: inline-block;
  padding: 10px 24px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: var(--main-primary, #dd8448);
  border-radius: 10px;
  text-decoration: none;
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.empty-cta:hover {
  opacity: 0.9;
  transform: translateY(-1px);
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
