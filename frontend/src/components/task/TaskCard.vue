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
          <!-- 已完成任務的按鈕行 -->
          <div v-if="task.status === 'completed'" class="completed-actions-row">
            <!-- Keep Audio 切換開關 -->
            <div
              v-if="task.result?.audio_file || task.audio_file"
              class="keep-audio-toggle"
              :title="getKeepAudioTooltip()"
            >
              <label class="toggle-label">
                <div class="toggle-knob-wrapper">
                  <input
                    type="checkbox"
                    :checked="task.keep_audio"
                    @change="handleToggleKeepAudio"
                    :disabled="!task.keep_audio && keepAudioCount >= 3"
                    class="toggle-input"
                  />
                  <!-- 扇形灰底 -->
                  <svg class="knob-arc-bg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40">
                    <path d="M 20 22 L 9.7 9.7 A 16 16 0 0 1 30.3 9.7 Z" fill="currentColor"/>
                  </svg>
                  <!-- 點（10點鐘方向） -->
                  <span class="knob-dot unlock-icon"></span>
                  <!-- 上鎖圖標（2點鐘方向） -->
                  <svg class="knob-lock-icon locked-icon" xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                  </svg>
                  <!-- 旋鈕 -->
                  <span class="toggle-knob">
                    <svg class="knob-indicator" xmlns="http://www.w3.org/2000/svg" width="12" height="36" viewBox="0 0 12 36">
                      <!-- 主指針：長方形 -->
                      <rect x="5" y="1" width="2" height="17" rx="1" fill="currentColor"/>
                      <!-- 圓心：圓形 -->
                      <circle cx="6" cy="18" r="3" fill="currentColor"/>
                      <!-- 尾巴：長方形 -->
                      <rect x="5" y="20" width="2" height="6" rx="1" fill="currentColor"/>
                    </svg>
                  </span>
                </div>
                <span v-if="isNewest" class="newest-badge" :title="$t('taskList.newestTaskAudioKept')">
                  {{ $t('taskList.newestBadge') }}
                </span>
              </label>
            </div>

            <!-- 雙聯按鈕組 -->
            <div class="btn-group">
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
  /* margin-bottom: -40px; */
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
  padding: 28px 20px 28px 20px;
  /* margin-left: 10px; */
  transition: all 0.3s;
  position: relative;
  /* background: var(--upload-bg); */
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
  /* filter: drop-shadow(0 6px 12px rgba(var(--color-primary-rgb), 0.2)); */
  transform: translateY(-2px);
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
  font-weight: 450;
  color: var(--nav-text);
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
  color: var(--color-info);
}

.badge-processing {
  background: rgba(var(--color-primary-rgb), 0.15);
  color: var(--color-primary);
}

.badge-completed {
  background: rgba(var(--color-success-rgb), 0.15);
  color: var(--color-success-light);
}

.badge-failed {
  background: rgba(var(--color-danger-rgb), 0.15);
  color: var(--color-danger);
}

.badge-cancelled {
  background: rgba(107, 114, 128, 0.15);
  color: var(--color-neutral-light);
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
  background: var(--color-teal-light);
  border-color: var(--color-teal-light);
  color: rgba(255, 255, 255, 0.95);
}

.badge-subtitle {
  background: var(--color-teal);
  border-color: var(--color-teal);
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
  background: var(--color-gray-100);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--color-primary) 0%, var(--color-primary-light) 100%);
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
  color: var(--color-danger);
}

/* 操作按鈕區域 */
.task-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-end;
  flex-shrink: 0;
}

/* 已完成任務的按鈕行 */
.completed-actions-row {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 12px;
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
  padding: 0px 5px;
  position: relative;
  /* border: 2px solid var(--nav-text); */
  border-radius: 10%;
}

/* 旋鈕式切換開關 */
.toggle-knob-wrapper {
  position: relative;
  width: 40px;
  height: 34px;
  display: inline-block;
}

.toggle-knob-wrapper .toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

/* 扇形灰底 */
.knob-arc-bg {
  position: absolute;
  width: 40px;
  height: 40px;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -45%);
  color: rgba(0, 0, 0, 0.08);
  pointer-events: none;
}

/* 鎖頭圖標 - 外圈位置 */
.knob-lock-icon {
  position: absolute;
  transition: all 0.3s ease;
  z-index: 1;
  pointer-events: none;
}

/* 點樣式（10點鐘方向） */
.knob-dot.unlock-icon {
  position: absolute;
  top: 5px;
  left: -1px;
  width: 5px;
  height: 5px;
  background: var(--color-gray-300);
  border-radius: 50%;
  transition: all 0.3s ease;
  opacity: 1;
}

.knob-lock-icon.locked-icon {
  /* 2點鐘方向 */
  top: 2px;
  right: -4px;
  color: rgb(177, 79, 22);
  /* filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3)); */
  opacity: 0.4;
}

/* 旋鈕主體 */
.toggle-knob {
  position: absolute;
  top: 65%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 32px;
  height: 32px;
  /* background: var(--color-gray-100); */
  border-radius: 50%;
  /* border: 0.9px solid var(--nav-text); */
  cursor: pointer;
  transition: all 0.3s ease;
  /* box-shadow:
    0 2px 4px rgba(0, 0, 0, 0.15),
    inset 0 1px 1px rgba(255, 255, 255, 0.8); */
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 旋鈕指示線 - 手錶指針風格 SVG */
.knob-indicator {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: #30302f;
  transition: all 0.3s ease;
}

/* 未選中狀態 - 10點鐘方向 (-60度) */
.toggle-input:not(:checked) ~ .toggle-knob {
  transform: translate(-50%, -50%) rotate(-40deg);
}

/* 選中狀態 - 2點鐘方向 (60度) */
.toggle-input:checked ~ .toggle-knob {
  transform: translate(-50%, -50%) rotate(40deg);

  color: #ec6f16;
  /* background: #e4811e; */
  /* box-shadow:
    0 2px 6px rgba(var(--color-primary-rgb), 0.4),
    inset 0 1px 1px rgba(255, 255, 255, 0.3); */
}

.toggle-input:checked ~ .toggle-knob .knob-indicator {
  color: rgb(203, 85, 5);
}

/* 選中時的圖標狀態 */
.toggle-input:checked ~ .knob-dot.unlock-icon {
  opacity: 0.4;
}

.toggle-input:checked ~ .knob-lock-icon.locked-icon {
  opacity: 1;
}

/* 禁用狀態 */
.toggle-input:disabled ~ .toggle-knob {
  opacity: 0.5;
  cursor: not-allowed;
}

.toggle-input:disabled ~ .knob-lock-icon,
.toggle-input:disabled ~ .knob-dot {
  opacity: 0.3;
}

/* hover 效果 */
.toggle-label:hover .toggle-knob {
  transform: translate(-50%, -50%) rotate(-40deg) scale(1.05);
}

.toggle-label:hover .toggle-input:checked ~ .toggle-knob {
  transform: translate(-50%, -50%) rotate(40deg) scale(1.05);
  /* box-shadow:
    0 3px 8px rgba(var(--color-primary-rgb), 0.5),
    inset 0 1px 1px rgba(255, 255, 255, 0.3); */
}

.toggle-label:hover .toggle-input:disabled ~ .toggle-knob {
  transform: translate(-50%, -50%) rotate(-40deg) scale(1);
}

.toggle-label:hover .toggle-input:disabled:checked ~ .toggle-knob {
  transform: translate(-50%, -50%) rotate(40deg) scale(1);
}

.newest-badge {
  position: absolute;
  top: -14px;
  right: -10px;
  padding: 1px 4px;
  font-size: 11px;
  font-weight: 600;
  background: var(--gradient-danger);
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
  background: #00000000;
  color: var(--nav-text);
}

.btn-download:hover {
  background: #00000000;
}

.btn-danger {
  background: #00000000;
  color: var(--nav-text);
}

.btn-danger:hover {
  background: #00000000;
}

.btn-warning {
  background: rgba(245, 158, 11, 0.15);
  color: var(--color-warning);
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
  border: 1.5px solid var(--nav-text);
  border-radius: 10%;
  /* border-top-right-radius: 0;
  border-bottom-right-radius: 0; */
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
