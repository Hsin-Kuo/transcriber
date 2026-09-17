<template>
  <div
    class="electric-card task-wrapper"
    :data-tour="task.__demo ? 'demo-card' : undefined"
  >
    <!-- 手機：左滑露出的快捷動作列（桌機 display:none，恆不影響桌機） -->
    <div class="swipe-actions-row" :style="{ width: swipeActionsWidth + 'px' }">
      <button
        v-if="task.status === 'completed'"
        type="button"
        class="swipe-action swipe-action-download"
        @click.stop="handleSwipeDownload"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="7 10 12 15 17 10"></polyline>
          <line x1="12" y1="15" x2="12" y2="3"></line>
        </svg>
        <span>{{ $t('taskList.downloadTranscript') }}</span>
      </button>
      <button
        v-if="!['pending', 'processing'].includes(task.status)"
        type="button"
        class="swipe-action swipe-action-tags"
        @click.stop="handleSwipeTags"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
          <line x1="7" y1="7" x2="7.01" y2="7"></line>
        </svg>
        <span>{{ $t('taskList.editTags') }}</span>
      </button>
      <button
        v-if="['pending', 'processing'].includes(task.status)"
        type="button"
        class="swipe-action swipe-action-cancel"
        :disabled="task.cancelling"
        @click.stop="handleSwipeCancel"
      >
        <span v-if="task.cancelling" class="spinner"></span>
        <template v-else>
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="15" y1="9" x2="9" y2="15"></line>
            <line x1="9" y1="9" x2="15" y2="15"></line>
          </svg>
        </template>
        <span>{{ $t('taskList.cancel') }}</span>
      </button>
      <button
        v-if="!['pending', 'processing'].includes(task.status)"
        type="button"
        class="swipe-action swipe-action-delete"
        @click.stop="handleSwipeDelete"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          <line x1="10" y1="11" x2="10" y2="17"></line>
          <line x1="14" y1="11" x2="14" y2="17"></line>
        </svg>
        <span>{{ $t('taskList.deleteTask') }}</span>
      </button>
    </div>

    <div
      class="task-item swipe-surface"
      :class="{
        'animated': ['pending', 'processing'].includes(task.status),
        'batch-edit-mode': isBatchMode,
        'clickable': task.status === 'completed' && !isBatchMode
      }"
      :style="swipeSurfaceStyle"
      :role="task.status === 'completed' && !isBatchMode ? 'link' : undefined"
      :tabindex="task.status === 'completed' && !isBatchMode ? 0 : undefined"
      @click.capture="swipeHandlers.onClickCapture"
      @click="handleCardClick"
      @keydown.enter="handleCardClick"
      @pointerdown="swipeHandlers.onPointerdown"
      @pointermove="swipeHandlers.onPointermove"
      @pointerup="swipeHandlers.onPointerup"
      @pointercancel="swipeHandlers.onPointercancel"
    >
      <!-- 批次編輯選擇框（進出場動畫：寬度展開＋縮放淡入，讓卡片內容平滑讓位） -->
      <Transition name="batch-check">
        <div v-if="isBatchMode" class="batch-select-checkbox" @click.stop>
          <input
            type="checkbox"
            :checked="isSelected"
            @change="emit('toggle-selection', task.task_id)"
            class="batch-checkbox"
            :aria-label="$t('taskList.selectTask')"
          />
        </div>
      </Transition>

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
            <!-- 創建時間 -->
            <span v-if="task.timestamps?.created_at || task.created_at" class="meta-item">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <polyline points="12 6 12 12 16 14"></polyline>
              </svg>
              {{ formatTimestamp(task.timestamps?.created_at || task.created_at) }}
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
            <div class="progress-bar" role="progressbar" :aria-valuenow="task.progress" aria-valuemin="0" aria-valuemax="100" :aria-label="$t('taskList.taskProgress')">
              <div
                class="progress-fill"
                :style="{ width: getProgressWidth(task) }"
              ></div>
            </div>
          </div>

          <!-- 錯誤訊息 -->
          <div v-if="task.status === 'failed'" class="task-error">
            {{ $t(`taskErrors.${typeof task.error === 'object' ? task.error?.code : task.error}`, $t('taskErrors.SYSTEM_ERROR')) }}
          </div>
        </div>

        <!-- 操作按鈕區域 -->
        <div class="task-actions" @click.stop>
          <!-- 已完成任務的按鈕行 -->
          <div v-if="task.status === 'completed'" class="completed-actions-row">
            <!-- Keep Audio 切換開關（桌機 + 手機皆顯示） -->
            <div
              v-if="task.result?.audio_file || task.audio_file"
              class="keep-audio-toggle"
              :title="getKeepAudioTooltip()"
            >
              <label class="toggle-label">
                <div class="toggle-pin-wrapper">
                  <input
                    ref="keepAudioCheckbox"
                    type="checkbox"
                    :checked="task.keep_audio"
                    @change="handleToggleKeepAudio"
                    :disabled="!task.keep_audio && keepAudioCount >= maxKeepAudio"
                    class="toggle-input"
                  />
                  <!-- 圖釘（線條風格） -->
                  <svg class="pin-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M9 4v6l-2 4v2h10v-2l-2-4V4" />
                    <line x1="12" y1="16" x2="12" y2="21" />
                    <line x1="8" y1="4" x2="16" y2="4" />
                  </svg>
                </div>
                <span v-if="isNewest" class="newest-badge" :title="$t('taskList.newestTaskAudioKept')">
                  {{ $t('taskList.newestBadge') }}
                </span>
              </label>
            </div>

            <!-- 降級後釋放釘選的音檔：寬限期到期提示 -->
            <span
              v-if="audioGraceDate"
              class="audio-grace-badge"
              :title="$t('taskList.audioGraceTooltip', { date: audioGraceDate })"
            >
              {{ $t('taskList.audioGraceBadge', { date: audioGraceDate }) }}
            </span>

            <!-- 桌機：雙聯按鈕組 -->
            <div class="btn-group desktop-action">
              <button
                class="btn btn-download btn-group-left btn-icon"
                @click.stop="emit('download', task)"
                :title="$t('taskList.downloadTranscript')"
                :aria-label="$t('taskList.downloadTranscript')"
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
                :aria-label="$t('taskList.deleteTask')"
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

          <!-- 桌機：失敗或取消任務的刪除按鈕 -->
          <button
            v-if="['failed', 'cancelled'].includes(task.status)"
            class="btn btn-danger desktop-action"
            @click="emit('delete', task.task_id)"
            :title="$t('taskList.deleteTask')"
          >
            {{ $t('taskList.deleteButtonText') }}
          </button>

        </div>

      </div>
    </div>

    <!-- 手機：標籤指派/建立 Bottom Sheet（Teleport 到 body，位置無關） -->
    <TagPickerSheet
      v-model="showTagSheet"
      :task-id="task.task_id"
      :tags="task.tags || []"
      :all-tags="allTags"
      @tags-updated="handleTagsUpdated"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTaskHelpers } from '../../composables/task/useTaskHelpers'
import { useDateFormatter } from '../../composables/useDateFormatter'
import { useAuthStore } from '../../stores/auth'
import { useSwipeActions } from '../../composables/task/useSwipeActions'
import TaskTagsSection from './TaskTagsSection.vue'
import TagPickerSheet from './TagPickerSheet.vue'

const { t: $t } = useI18n()
const authStore = useAuthStore()

// 手動保留音檔上限（依方案）；999999 視為無限
const UNLIMITED_KEEP_AUDIO = 999999
const maxKeepAudio = computed(() => authStore.maxKeepAudio)
const isUnlimitedKeepAudio = computed(() => maxKeepAudio.value >= UNLIMITED_KEEP_AUDIO)
const { formatDateTime: formatTimestamp, formatDate } = useDateFormatter()
const {
  getStatusText,
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
  'long-press',
  'toggle-keep-audio',
  'tags-updated'
])

// 左滑動作列：每顆按鈕 >=64px，寬度依狀態顯示的按鈕數決定
const SWIPE_ACTION_BTN_WIDTH = 68
const swipeActionCount = computed(() => {
  if (props.task.status === 'completed') return 3 // 下載/標籤/刪除
  if (['pending', 'processing'].includes(props.task.status)) return 2 // 標籤/取消
  return 2 // failed/cancelled：標籤/刪除
})
const swipeActionsWidth = computed(() => swipeActionCount.value * SWIPE_ACTION_BTN_WIDTH)
const swipeDisabled = computed(() => props.isBatchMode)

const {
  offsetX: swipeOffsetX,
  withTransition: swipeWithTransition,
  handlers: swipeHandlers,
  closeSwipe
} = useSwipeActions(props.task.task_id, swipeActionsWidth, swipeDisabled, () => {
  // 長按 500ms：進入批次選取模式並勾選本卡（手機原生慣例）
  emit('long-press', props.task.task_id)
})

// 進入批次編輯模式時，強制收合已開啟的滑動動作列
watch(swipeDisabled, (disabled) => {
  if (disabled) closeSwipe(false)
})

const swipeSurfaceStyle = computed(() => ({
  transform: `translateX(${swipeOffsetX.value}px)`,
  transition: swipeWithTransition.value ? 'transform 0.25s ease' : 'none'
}))

function handleSwipeDownload() {
  closeSwipe()
  emit('download', props.task)
}

function handleSwipeTags() {
  closeSwipe()
  openTagSheet()
}

function handleSwipeDelete() {
  closeSwipe()
  emit('delete', props.task.task_id)
}

function handleSwipeCancel() {
  closeSwipe()
  emit('cancel', props.task.task_id)
}

// 標籤 Bottom Sheet（由左滑動作列的「標籤」鈕開啟）
const showTagSheet = ref(false)

function openTagSheet() {
  showTagSheet.value = true
}

// Methods
function handleCardClick(e) {
  // Enter 從卡片內部互動元素（input / button / a / textarea / contenteditable）冒泡上來時，
  // 代表使用者意圖在操作那個元素（如新增標籤、按刪除按鈕），不該再觸發整張卡片導航。
  if (e?.type === 'keydown') {
    const t = e.target
    const tag = t?.tagName
    if (tag === 'INPUT' || tag === 'BUTTON' || tag === 'TEXTAREA' || tag === 'A' || t?.isContentEditable) {
      return
    }
  }
  if (props.task.status === 'completed' && !props.isBatchMode) {
    emit('view', props.task.task_id)
  }
}

const keepAudioCheckbox = ref(null)

function handleToggleKeepAudio() {
  // 取消釘選時，提醒用戶音檔可能被刪除
  if (props.task.keep_audio) {
    if (!confirm($t('taskList.confirmUnpinAudio'))) {
      // 恢復 checkbox 狀態
      if (keepAudioCheckbox.value) {
        keepAudioCheckbox.value.checked = true
      }
      return
    }
  }
  emit('toggle-keep-audio', props.task)
}

function handleTagsUpdated(data) {
  emit('tags-updated', data)
}

// 降級釋放的音檔寬限期到期日（後端寫入 audio_expires_at）。
// 後端在超過寬限期時會把 audio_file 隱藏，故有 audio_file + audio_expires_at 即代表仍在寬限期內。
const audioGraceDate = computed(() => {
  const ts = props.task.audio_expires_at
  if (!ts) return null
  const hasAudio = props.task.result?.audio_file || props.task.audio_file
  if (!hasAudio) return null
  return formatDate(ts)
})

function getKeepAudioTooltip() {
  // 最新任務音檔自動保留，不受手動額度影響（不帶數字，避免 free=0 / 無限方案顯示怪異）
  if (props.isNewest) {
    return $t('taskList.keepAudioTooltipNewest')
  }
  // 方案不支援手動保留（free，max_keep_audio=0）
  if (maxKeepAudio.value <= 0) {
    return $t('taskList.keepAudioTooltipUnavailable')
  }
  // 已達上限
  if (!props.task.keep_audio && props.keepAudioCount >= maxKeepAudio.value) {
    return $t('taskList.keepAudioTooltipFull', { n: maxKeepAudio.value })
  }
  // 無限方案不秀數字
  if (isUnlimitedKeepAudio.value) {
    return $t('taskList.keepAudioTooltipNormalUnlimited')
  }
  return $t('taskList.keepAudioTooltipNormal', { n: maxKeepAudio.value })
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

/* 左滑動作列：手機才顯示（見下方 @media），桌機恆 display:none，零視覺影響 */
.swipe-actions-row {
  display: none;
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 1;
  overflow: hidden;
}

.swipe-action {
  flex: 1 0 68px;
  min-width: 64px;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  border: none;
  cursor: pointer;
  font-size: 11px;
  font-weight: 500;
  color: #fff;
  padding: 0 4px;
}

.swipe-action span {
  line-height: 1.2;
  text-align: center;
}

.swipe-action-download {
  background: var(--color-primary);
}

.swipe-action-tags {
  background: var(--color-neutral, #6b7280);
}

.swipe-action-cancel {
  background: var(--color-warning, #f59e0b);
}

.swipe-action-delete {
  background: var(--color-danger, #ef4444);
}

.swipe-action:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 手機滑動層：桌機下 transform 恆為 0、touch-action 不影響滑鼠操作 */
.swipe-surface {
  width: 100%;
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
  max-width: 32px;
}

/* 進出批次模式的過渡：寬度 0→32px 展開（內容平滑讓位）＋縮放淡入 */
.batch-check-enter-active,
.batch-check-leave-active {
  transition: max-width 0.25s ease, opacity 0.2s ease, transform 0.25s ease;
  overflow: hidden;
}

.batch-check-enter-from,
.batch-check-leave-to {
  max-width: 0;
  opacity: 0;
  transform: scale(0.5);
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

/* pending 在 UI 上比照 processing 呈現（內部 status 仍為 pending） */
.badge-pending,
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

.badge-task-type {
  padding: 2px 8px;
  border-radius: 4px;
  
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
  border: 1px solid;
}

/* .badge-paragraph {
  background: var(--color-teal-light);
  border-color: var(--color-teal-light);
  color: rgba(255, 255, 255, 0.95);
} */
/* 
.badge-subtitle {
  background: var(--color-teal);
  border-color: var(--color-teal);
  color: rgba(255, 255, 255, 0.95);
} */

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
  /* gap: 12px; */
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

/* 圖釘式切換開關 */
.toggle-pin-wrapper {
  position: relative;
  width: 32px;
  height: 32px;
  display: inline-block;
}

.toggle-pin-wrapper .toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

/* 圖釘圖標 */
.pin-icon {
  position: absolute;
  width: 24px;
  height: 24px;
  top: 50%;
  left: 50%;
  color: var(--color-text-light);
  cursor: pointer;
  transition: all 0.3s ease;
  transform-origin: center 30%;
}

/* 未選中狀態 - 傾斜 */
.toggle-input:not(:checked) ~ .pin-icon {
  transform: translate(-50%, -50%) rotate(35deg);
  color: var(--nav-text);
  opacity: 1;
}

/* 選中狀態 - 垂直插入 */
.toggle-input:checked ~ .pin-icon {
  transform: translate(-50%, -50%) rotate(0deg);
  color: var(--color-primary);
  opacity: 1;
}

/* 禁用狀態 */
.toggle-input:disabled ~ .pin-icon {
  opacity: 0.4;
  cursor: not-allowed;
}

/* hover 效果 */
.toggle-label:hover .toggle-input:not(:disabled):not(:checked) ~ .pin-icon {
  transform: translate(-50%, -50%) rotate(35deg) scale(1.08);
  color: var(--color-text-muted);
}

.toggle-label:hover .toggle-input:not(:disabled):checked ~ .pin-icon {
  transform: translate(-50%, -50%) rotate(0deg) scale(1.08);
  color: var(--color-primary-light);
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

/* 降級後寬限期到期提示 badge */
.audio-grace-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  color: #856404;
  background: #fff3cd;
  border: 1px solid #f59e0b;
  border-radius: 999px;
  white-space: nowrap;
  cursor: help;
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
  /* border: 1.5px solid var(--nav-text); */
  border-radius: 10%;
  /* border-top-right-radius: 0;
  border-bottom-right-radius: 0; */
}

.btn-group-right {
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  /* border-left: 1px solid rgba(255, 255, 255, 0.3); */
}

.btn-group .btn {
  box-shadow: none !important;
}

/* 桌機/手機顯示切換（kebab 已移除，手機快捷操作改由左滑動作列提供） */
.desktop-action { display: flex; }

/* === 響應式設計 === */

/* 平板以下 */
@media (max-width: 768px) {
  .task-item {
    padding: 20px 16px;
    clip-path: polygon(
      20px 0,
      100% 0,
      100% 100%,
      0 100%,
      0 20px
    );
  }

  /* 左滑動作列只在手機啟用；.task-item 需要不透明背景才能在收合時遮住動作列 */
  .swipe-actions-row {
    display: flex;
  }

  .swipe-surface {
    position: relative;
    z-index: 2;
    /* 與 body 同色：滑動需要不透明底蓋住動作鈕，用頁面底色讓卡片維持原本
       「透明」觀感。用 --color-bg 不用 --main-bg——後者在卡片祖先層被覆寫成
       不同值（實測 #e6e6e6 vs body #f5f5f5） */
    background-color: var(--color-bg);
    touch-action: pan-y;
  }

  /* 保持按鈕與標題同行 */
  .task-main {
    flex-direction: row;
    align-items: flex-start;
    gap: 12px;
  }

  .task-header {
    flex-wrap: wrap;
    gap: 8px;
  }

  .task-header h3 {
    font-size: var(--font-size-lg);
    word-break: break-word;
  }

  .task-meta {
    gap: 10px;
    font-size: 12px;
  }

  .task-actions {
    flex-shrink: 0;
  }

  /* 手機：隱藏桌機按鈕（快捷操作改由左滑動作列提供） */
  .desktop-action { display: none; }


  .btn {
    padding: 8px 12px;
  }

  .btn-icon {
    padding: 8px;
  }
}

/* 小手機 */
@media (max-width: 480px) {
  .task-item {
    padding: 14px 10px;
    gap: 6px;
    clip-path: polygon(
      14px 0,
      100% 0,
      100% 100%,
      0 100%,
      0 14px
    );
  }

  .task-main {
    gap: 8px;
  }

  .task-header {
    margin-bottom: 6px;
    padding-bottom: 4px;
  }

  .task-header h3 {
    font-size: var(--font-size-lg);
  }

  .task-divider {
    font-size: 11px;
  }

  .badge {
    font-size: 10px;
    padding: 1px 5px;
  }

  .task-meta {
    gap: 6px;
    font-size: 10px;
    margin-bottom: 6px;
  }

  .task-meta .meta-item svg {
    width: 11px;
    height: 11px;
  }

  .badge-task-type {
    font-size: 10px;
    padding: 1px 5px;
  }

  /* 進度條 */
  .task-progress {
    margin-top: 6px;
  }

  .progress-text {
    font-size: 11px;
  }

  /* 操作按鈕 - 更緊湊 */
  .completed-actions-row {
    gap: 2px;
  }

  .keep-audio-toggle {
    gap: 2px;
  }

  .toggle-pin-wrapper {
    width: 24px;
    height: 24px;
  }

  .pin-icon {
    width: 16px;
    height: 16px;
  }

  .newest-badge {
    font-size: 9px;
    top: -10px;
    right: -6px;
    padding: 0px 3px;
  }

  .btn {
    padding: 6px;
    font-size: 11px;
    min-height: auto;
  }

  .btn-icon {
    padding: 6px;
  }

  .btn-icon svg {
    width: 14px;
    height: 14px;
  }

  /* 批次選擇框 */
  .batch-checkbox {
    width: 18px;
    height: 18px;
  }

  /* 錯誤訊息 */
  .task-error {
    font-size: 11px;
    padding: 5px 8px;
  }
}

</style>
