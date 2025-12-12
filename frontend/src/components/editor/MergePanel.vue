<template>
  <div class="merge-panel electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main panel-content">
          <div class="panel-header">
            <h3>🔗 合併片段</h3>
          </div>

          <div class="mode-selector">
            <label class="mode-label">合併模式:</label>
            <div class="mode-options">
              <button
                @click="$emit('mode-changed', 'same-file-clips')"
                :class="['mode-btn', { active: mode === 'same-file-clips' }]"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                  <line x1="9" y1="9" x2="15" y2="9"></line>
                  <line x1="9" y1="15" x2="15" y2="15"></line>
                </svg>
                同檔片段
              </button>
              <button
                @click="$emit('mode-changed', 'different-files')"
                :class="['mode-btn', { active: mode === 'different-files' }]"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                  <polyline points="13 2 13 9 20 9"></polyline>
                </svg>
                不同檔案
              </button>
            </div>
          </div>

          <div class="mode-description">
            <p v-if="mode === 'same-file-clips'">
              💡 將選取的片段按順序合併成一個檔案（適合從同一音檔剪輯多個片段後合併）
            </p>
            <p v-else>
              💡 將多個不同的音檔按順序合併成一個檔案（適合合併不同的錄音片段）
            </p>
          </div>

          <div class="clip-selection">
            <div class="selection-header">
              <span>選擇要合併的片段：</span>
              <button @click="selectAll" class="text-btn">
                {{ selectedClips.length === clips.length ? '取消全選' : '全選' }}
              </button>
            </div>

            <div v-if="clips.length === 0" class="empty-state">
              <p>無可用片段</p>
              <p class="hint">請先剪輯音訊片段</p>
            </div>

            <div v-else class="clips-selection-list">
              <label
                v-for="clip in clips"
                :key="clip.id"
                class="clip-checkbox"
              >
                <input
                  type="checkbox"
                  :value="clip.id"
                  v-model="selectedClips"
                  @change="updateSelection"
                />
                <span class="checkbox-custom"></span>
                <span class="clip-label">
                  <span class="clip-name">{{ clip.name }}</span>
                  <span class="clip-duration">{{ formatDuration(clip.duration) }}</span>
                </span>
              </label>
            </div>
          </div>

          <button
            @click="handleMerge"
            :disabled="selectedClips.length < 2"
            class="btn btn-merge"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M16 3h5v5"></path>
              <path d="M8 3H3v5"></path>
              <path d="M12 22v-7"></path>
              <path d="M3 8s3-2 9-2 9 2 9 2"></path>
            </svg>
            合併選取片段 ({{ selectedClips.length }})
          </button>
        </div>
      </div>
      <div class="electric-glow-1"></div>
      <div class="electric-glow-2"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  clips: {
    type: Array,
    default: () => []
  },
  mode: {
    type: String,
    default: 'same-file-clips'
  }
})

const emit = defineEmits(['mode-changed', 'merge'])

const selectedClips = ref([])

watch(() => props.clips, () => {
  // 清除無效的選擇
  selectedClips.value = selectedClips.value.filter(id =>
    props.clips.some(clip => clip.id === id)
  )
})

function selectAll() {
  if (selectedClips.value.length === props.clips.length) {
    selectedClips.value = []
  } else {
    selectedClips.value = props.clips.map(c => c.id)
  }
}

function updateSelection() {
  // 確保選擇順序與顯示順序一致
}

function handleMerge() {
  const selected = props.clips.filter(c => selectedClips.value.includes(c.id))
  emit('merge', selected)
}

function formatDuration(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}
</script>

<style scoped>
.panel-content {
  padding: 24px;
  background: linear-gradient(135deg, rgba(28, 28, 28, 0.95) 0%, rgba(20, 20, 20, 0.95) 100%);
}

.panel-header h3 {
  margin: 0 0 20px 0;
  font-size: 1.3rem;
  color: #fff;
}

.mode-selector {
  margin-bottom: 16px;
}

.mode-label {
  display: block;
  color: #aaa;
  font-size: 0.9rem;
  margin-bottom: 8px;
}

.mode-options {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.mode-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 16px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  color: #aaa;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
}

.mode-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.mode-btn.active {
  background: rgba(156, 39, 176, 0.2);
  color: #9C27B0;
  border-color: rgba(156, 39, 176, 0.5);
}

.mode-description {
  margin-bottom: 20px;
  padding: 12px;
  background: rgba(156, 39, 176, 0.1);
  border-radius: 6px;
  border-left: 3px solid #9C27B0;
}

.mode-description p {
  margin: 0;
  color: #bbb;
  font-size: 0.85rem;
  line-height: 1.5;
}

.clip-selection {
  margin-bottom: 20px;
}

.selection-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: #aaa;
  font-size: 0.9rem;
}

.text-btn {
  background: none;
  border: none;
  color: #9C27B0;
  cursor: pointer;
  font-size: 0.85rem;
  text-decoration: underline;
  padding: 0;
}

.text-btn:hover {
  color: #BA68C8;
}

.empty-state {
  text-align: center;
  padding: 30px 20px;
  color: #888;
}

.empty-state p {
  margin: 6px 0;
}

.hint {
  font-size: 0.85rem;
  color: #666;
}

.clips-selection-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 250px;
  overflow-y: auto;
}

.clip-checkbox {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.clip-checkbox:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(156, 39, 176, 0.3);
}

.clip-checkbox input[type="checkbox"] {
  display: none;
}

.checkbox-custom {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 4px;
  position: relative;
  transition: all 0.2s ease;
}

.clip-checkbox input[type="checkbox"]:checked + .checkbox-custom {
  background: #9C27B0;
  border-color: #9C27B0;
}

.clip-checkbox input[type="checkbox"]:checked + .checkbox-custom::after {
  content: '';
  position: absolute;
  left: 5px;
  top: 2px;
  width: 5px;
  height: 10px;
  border: solid white;
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}

.clip-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex: 1;
}

.clip-name {
  color: #fff;
  font-weight: 500;
}

.clip-duration {
  color: #9C27B0;
  font-weight: 600;
  font-size: 0.85rem;
  font-family: 'Courier New', monospace;
}

.btn-merge {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 14px 24px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #9C27B0 0%, #BA68C8 100%);
  color: white;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.btn-merge:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 8px 16px rgba(156, 39, 176, 0.3);
}

.btn-merge:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.clips-selection-list::-webkit-scrollbar {
  width: 6px;
}

.clips-selection-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
}

.clips-selection-list::-webkit-scrollbar-thumb {
  background: rgba(156, 39, 176, 0.5);
  border-radius: 3px;
}

.clips-selection-list::-webkit-scrollbar-thumb:hover {
  background: rgba(156, 39, 176, 0.7);
}
</style>
