<template>
  <div
    class="electric-card task-wrapper"
  >
    <div
      class="task-item"
      :class="{
        'animated': task.status === 'processing',
        'batch-edit-mode': isBatchMode,
        'clickable': task.status === 'completed' && !isBatchMode
      }"
      @click="handleCardClick"
    >
      <!-- 批次編輯選擇框 -->
      <div v-if="isBatchMode" class="batch-select-checkbox" @click.stop>
        <input
          type="checkbox"
          :checked="isSelected"
          @change="emit('toggle-selection', task.task_id)"
          class="batch-checkbox"
        />
      </div>

      <div class="task-main">
        <div class="task-info">
          <!-- 任務標題和狀態 -->
          <div class="task-header">
            <h3>{{ task.custom_name || task.file?.filename || task.filename || task.file }}</h3>
            <template v-if="task.status !== 'completed'">
              <span class="task-divider">/</span>
              <span :class="['badge', `badge-${task.status}`]">
                {{ getStatusText(task.status) }}
              </span>
            </template>
          </div>

          <!-- 任務元數據 -->
          <div class="task-meta">
            <!-- 音訊時長 -->
            <span v-if="getAudioDuration(task)" class="meta-item">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 18V5l12-2v13"></path>
                <circle cx="6" cy="18" r="3"></circle>
                <circle cx="18" cy="16" r="3"></circle>
              </svg>
              {{ getAudioDuration(task) }}
            </span>

            <!-- 創建時間 -->
            <span v-if="task.timestamps?.created_at || task.created_at" class="meta-item">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
              </svg>
              {{ task.timestamps?.created_at || task.created_at }}
            </span>

            <!-- 任務類型 -->
            <span v-if="task.task_type" class="badge-task-type" :class="`badge-${task.task_type}`">
              {{ task.task_type === 'subtitle' ? $t('taskList.subtitle') : $t('taskList.paragraph') }}
            </span>

            <!-- 標籤區域（使用 TaskTagsSection 組件） -->
            <TaskTagsSection
              :task-id="task.task_id"
              :tags="task.tags"
              :all-tags="allTags"
              @tags-updated="handleTagsUpdated"
            />
          </div>

          <!-- 進度條（僅 pending 和 processing 狀態） -->
          <div v-if="task.progress && isTaskExpanded(task.task_id, [task])" class="task-progress">
            <div class="progress-bar">
              <div
                class="progress-fill"
                :style="{ width: getProgressWidth(task) }"
              ></div>
            </div>
            <p class="progress-text">
              <span v-if="['pending', 'processing', 'canceling'].includes(task.status)" class="spinner"></span>
              {{ task.progress }}
              <span v-if="task.progress_percentage !== undefined && task.progress_percentage !== null" class="progress-percentage">
                {{ Math.round(task.progress_percentage) }}%
              </span>
            </p>
          </div>

          <!-- 錯誤訊息 -->
          <div v-if="task.status === 'failed' && task.error" class="task-error">
            {{ task.error }}
          </div>
        </div>

        <!-- 操作按鈕區域 -->
        <div class="task-actions" @click.stop>
          <!-- Keep Audio 切換開關 -->
          <div
            v-if="task.status === 'completed' && (task.result?.audio_file || task.audio_file)"
            class="keep-audio-toggle"
            :title="getKeepAudioTooltip()"
          >
            <label class="toggle-label">
              <div class="toggle-switch-wrapper">
                <input
                  type="checkbox"
                  :checked="task.keep_audio"
                  @change="handleToggleKeepAudio"
                  :disabled="!task.keep_audio && keepAudioCount >= 3"
                  class="toggle-input"
                />
                <span class="toggle-slider">
                  <!-- 解鎖圖標（未選中時顯示） -->
                  <svg class="lock-icon unlock-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 9.9-1"></path>
                  </svg>
                  <!-- 上鎖圖標（選中時顯示） -->
                  <svg class="lock-icon locked-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                  </svg>
                </span>
              </div>
              <span v-if="isNewest" class="newest-badge" :title="$t('taskList.newestTaskAudioKept')">
                {{ $t('taskList.newestBadge') }}
              </span>
            </label>
          </div>

          <!-- 已完成任務的雙聯按鈕組 -->
          <div v-if="task.status === 'completed'" class="btn-group">
            <button
              class="btn btn-download btn-group-left btn-icon"
              @click.stop="emit('download', task)"
              :title="$t('taskList.downloadTranscript')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
            </button>
            <button
              class="btn btn-danger btn-group-right btn-icon"
              @click.stop="emit('delete', task.task_id)"
              :title="$t('taskList.deleteTask')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                <line x1="10" y1="11" x2="10" y2="17"></line>
                <line x1="14" y1="11" x2="14" y2="17"></line>
              </svg>
            </button>
          </div>

          <!-- 進行中任務的取消按鈕 -->
          <button
            v-if="['pending', 'processing'].includes(task.status)"
            class="btn btn-warning"
            @click="emit('cancel', task.task_id)"
            :disabled="task.cancelling"
            :title="$t('taskList.cancelRunningTask')"
          >
            <span v-if="task.cancelling" class="spinner"></span>
            {{ task.cancelling ? $t('taskList.cancelling') : $t('taskList.cancel') }}
          </button>

          <!-- 失敗或取消任務的刪除按鈕 -->
          <button
            v-if="['failed', 'cancelled'].includes(task.status)"
            class="btn btn-danger"
            @click="emit('delete', task.task_id)"
            :title="$t('taskList.deleteTask')"
          >
            {{ $t('taskList.deleteButtonText') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { useTaskHelpers } from '../../composables/task/useTaskHelpers'
import TaskTagsSection from './TaskTagsSection.vue'

const { t: $t } = useI18n()
const {
  getStatusText,
  getAudioDuration,
  getProgressWidth,
  isTaskExpanded
} = useTaskHelpers($t)

// Props
const props = defineProps({
  task: {
    type: Object,
    required: true
  },
  isBatchMode: {
    type: Boolean,
    default: false
  },
  isSelected: {
    type: Boolean,
    default: false
  },
  isNewest: {
    type: Boolean,
    default: false
  },
  keepAudioCount: {
    type: Number,
    default: 0
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

// Methods
function handleCardClick() {
  if (props.task.status === 'completed' && !props.isBatchMode) {
    emit('view', props.task.task_id)
  }
}

function handleToggleKeepAudio() {
  emit('toggle-keep-audio', props.task)
}

function handleTagsUpdated(data) {
  emit('tags-updated', data)
}

function getKeepAudioTooltip() {
  if (props.isNewest) {
    return $t('taskList.keepAudioTooltipNewest')
  }
  if (!props.task.keep_audio && props.keepAudioCount >= 3) {
    return $t('taskList.keepAudioTooltipFull')
  }
  return $t('taskList.keepAudioTooltipNormal')
}
</script>

<style scoped>
/* Task Card 樣式 - 從 TaskList.vue.backup 完整複製 */

.electric-card.task-wrapper {
  position: relative;
  margin-bottom: -40px;
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.12));
}

.electric-card.task-wrapper:nth-child(1) { z-index: 91; }
.electric-card.task-wrapper:nth-child(2) { z-index: 92; }
.electric-card.task-wrapper:nth-child(3) { z-index: 93; }
.electric-card.task-wrapper:nth-child(4) { z-index: 94; }
.electric-card.task-wrapper:nth-child(5) { z-index: 95; }
.electric-card.task-wrapper:nth-child(6) { z-index: 96; }
.electric-card.task-wrapper:nth-child(7) { z-index: 97; }
.electric-card.task-wrapper:nth-child(8) { z-index: 98; }
.electric-card.task-wrapper:nth-child(9) { z-index: 99; }
.electric-card.task-wrapper:nth-child(10) { z-index: 100; }

.task-item {
  padding: 28px 20px 48px 20px;
  /* margin-left: 10px; */
  transition: all 0.3s;
  position: relative;
  background: var(--upload-bg);
  background-image:
    repeating-linear-gradient(0deg, transparent, transparent 9px, rgba(0, 0, 0, 0.015) 9px, rgba(0, 0, 0, 0.015) 10px),
    repeating-linear-gradient(90deg, transparent, transparent 9px, rgba(0, 0, 0, 0.015) 9px, rgba(0, 0, 0, 0.015) 10px);
  clip-path: polygon(
    25px 0,
    100% 0,
    100% 100%,
    0 100%,
    0 25px
  );
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.task-item.clickable {
  cursor: pointer;
}

.task-wrapper:hover .task-item {
  filter: drop-shadow(0 6px 12px rgba(var(--color-primary-rgb), 0.2));
  transform: translateY(-2px);
}

.task-wrapper:hover .task-item.clickable {
  filter: drop-shadow(0 8px 16px rgba(var(--color-primary-rgb), 0.25));
}

.task-item.batch-edit-mode {
  padding-left: 20px;
}

.task-item.animated {
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.95;
  }
}

.batch-select-checkbox {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  padding-top: 0;
  height: 24px;
  margin-left: -4px;
}

.batch-checkbox {
  width: 18px;
  height: 18px;
  cursor: pointer;
  margin: 0;
}

.task-main {
  flex: 1;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}

.task-info {
  flex: 1;
}

.task-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  padding-bottom: 6px;
}

.task-header h3 {
  font-size: 16px;
  color: #2d2d2d;
  margin: 0;
}

.task-divider {
  font-size: 14px;
  font-weight: 300;
  color: rgba(0, 0, 0, 0.3);
  margin: 0 -4px;
}

.task-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  margin-bottom: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.task-meta .meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.task-meta .meta-item svg {
  flex-shrink: 0;
  opacity: 0.7;
}

/* 徽章樣式 */
.badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.badge-pending {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.badge-processing {
  background: rgba(var(--color-primary-rgb), 0.15);
  color: var(--color-primary);
}

.badge-completed {
  background: rgba(var(--color-success-rgb), 0.15);
  color: #059669;
}

.badge-failed {
  background: rgba(var(--color-danger-rgb), 0.15);
  color: #ef4444;
}

.badge-cancelled {
  background: rgba(107, 114, 128, 0.15);
  color: #6b7280;
}

.badge-task-type,
.badge-diarize {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
  border: 1px solid;
}

.badge-paragraph {
  background: #808F7C;
  border-color: #808F7C;
  color: rgba(255, 255, 255, 0.95);
}

.badge-subtitle {
  background: #77969A;
  border-color: #77969A;
  color: rgba(255, 255, 255, 0.95);
}

.badge-diarize {
  background: rgba(246, 156, 92, 0.1);
  border-color: rgba(246, 141, 92, 0.3);
  color: rgba(217, 108, 40, 0.9);
}

/* 進度條 */
.task-progress {
  margin-top: 12px;
}

.progress-bar {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #dd8448 0%, #f59e42 100%);
  transition: width 0.5s ease;
  border-radius: 3px;
}

.progress-text {
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.8);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}

.progress-percentage {
  color: var(--electric-primary);
  font-weight: 600;
  margin-left: 8px;
}

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(var(--color-primary-rgb), 0.2);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 錯誤訊息 */
.task-error {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(var(--color-danger-rgb), 0.15);
  border: 1px solid rgba(var(--color-danger-rgb), 0.3);
  border-radius: 6px;
  font-size: 13px;
  color: #ef4444;
}

/* 操作按鈕區域 */
.task-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-end;
  flex-shrink: 0;
}

/* Keep Audio 切換開關 */
.keep-audio-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
  padding-right: 5px;
  position: relative;
}

.toggle-label:hover .toggle-slider {
  transform: scale(1.05);
}

.toggle-switch-wrapper {
  position: relative;
  width: 44px;
  height: 24px;
  display: inline-block;
}

.toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #ccc;
  transition: all 0.3s ease;
  border-radius: 24px;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.toggle-input:checked + .toggle-slider {
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%);
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1), 0 0 8px rgba(var(--color-primary-rgb), 0.3);
}

.toggle-input:checked + .toggle-slider:before {
  transform: translateX(20px);
}

.toggle-input:disabled + .toggle-slider {
  opacity: 0.5;
  cursor: not-allowed;
  background-color: #ddd;
}

.toggle-input:disabled + .toggle-slider:before {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}

.toggle-label:hover .toggle-slider:not(.toggle-input:disabled + .toggle-slider) {
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2), 0 0 4px rgba(0, 0, 0, 0.1);
}

.toggle-label:hover .toggle-input:checked + .toggle-slider {
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1), 0 0 12px rgba(var(--color-primary-rgb), 0.4);
}

.lock-icon {
  position: absolute;
  transition: all 0.3s ease;
  z-index: 1;
  pointer-events: none;
}

.unlock-icon {
  left: 6px;
  color: #888;
  opacity: 1;
}

.locked-icon {
  right: 6px;
  color: rgb(177, 79, 22);
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3));
  opacity: 0;
}

.toggle-input:not(:checked) + .toggle-slider .unlock-icon {
  opacity: 1;
}

.toggle-input:not(:checked) + .toggle-slider .locked-icon {
  opacity: 0;
}

.toggle-input:checked + .toggle-slider .unlock-icon {
  opacity: 0;
}

.toggle-input:checked + .toggle-slider .locked-icon {
  opacity: 1;
}

.toggle-input:disabled + .toggle-slider .lock-icon {
  opacity: 0.4;
}

.newest-badge {
  position: absolute;
  top: -14px;
  right: -10px;
  padding: 1px 4px;
  font-size: 11px;
  font-weight: 600;
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
  color: white;
  border-radius: 4px;
  box-shadow: 0 2px 4px rgba(255, 107, 107, 0.3);
  pointer-events: none;
}

/* 按鈕 */
.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

/* .btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
} */

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-icon {
  padding: 8px 12px;
}

.btn-download {
  background: rgba(var(--color-primary-rgb), 0.15);
  color: var(--color-primary);
}

.btn-download:hover {
  background: rgba(var(--color-primary-rgb), 0.25);
}

.btn-danger {
  background: rgba(var(--color-danger-rgb), 0.15);
  color: #ef4444;
}

.btn-danger:hover {
  background: rgba(var(--color-danger-rgb), 0.25);
}

.btn-warning {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}

.btn-warning:hover {
  background: rgba(245, 158, 11, 0.35);
}

/* 按鈕組 */
.btn-group {
  display: flex;
  gap: 0;
}

.btn-group-left {
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}

.btn-group-right {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  border-left: 1px solid rgba(255, 255, 255, 0.3);
}

.btn-group .btn {
  box-shadow: none !important;
}
</style>
