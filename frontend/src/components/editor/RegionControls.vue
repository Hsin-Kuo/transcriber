<template>
  <div class="region-controls electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main controls-content">
          <div class="controls-header">
            <h3>📍 選取區段</h3>
            <span class="region-count">{{ regions.length }} 個區段</span>
          </div>

          <div v-if="regions.length === 0" class="empty-state">
            <p>尚無選取區段</p>
            <p class="hint">點擊波形或使用「新增區段」按鈕來選取音訊片段</p>
          </div>

          <div v-else class="regions-list">
            <div
              v-for="(region, index) in regions"
              :key="region.id"
              class="region-item"
            >
              <div class="region-info">
                <span class="region-number">#{{ index + 1 }}</span>
                <div class="region-times">
                  <span class="time-label">起始:</span>
                  <span class="time-value">{{ formatTime(region.start) }}</span>
                  <span class="separator">→</span>
                  <span class="time-label">結束:</span>
                  <span class="time-value">{{ formatTime(region.end) }}</span>
                </div>
                <span class="region-duration">{{ formatDuration(region.duration) }}</span>
              </div>
              <div class="region-actions">
                <button
                  @click="handlePlayRegion(region)"
                  class="action-btn play-btn"
                  title="播放此區段"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3"></polygon>
                  </svg>
                </button>
                <button
                  @click="handleDeleteRegion(region.id)"
                  class="action-btn delete-btn"
                  title="刪除此區段"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="electric-glow-1"></div>
      <div class="electric-glow-2"></div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  regions: {
    type: Array,
    default: () => []
  },
  audioDuration: {
    type: Number,
    default: 0
  }
})

const emit = defineEmits(['add-region', 'delete-region', 'play-region'])

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  const ms = Math.floor((seconds % 1) * 10)
  return `${mins}:${secs.toString().padStart(2, '0')}.${ms}`
}

function formatDuration(seconds) {
  return `${seconds.toFixed(1)}s`
}

function handlePlayRegion(region) {
  console.log('🎵 Play region clicked:', region.id)
  emit('play-region', region)
}

function handleDeleteRegion(regionId) {
  console.log('🗑️ Delete region clicked:', regionId)
  emit('delete-region', regionId)
}
</script>

<style scoped>
.controls-content {
  padding: 24px;
  background: var(--editor-bg-gradient);
}

.controls-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.controls-header h3 {
  margin: 0;
  font-size: 1.3rem;
  color: var(--color-white);
}

.region-count {
  background: rgba(var(--color-primary-rgb), 0.2);
  color: var(--color-primary);
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 600;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-gray-300);
}

.empty-state p {
  margin: 8px 0;
}

.hint {
  font-size: 0.9rem;
  color: var(--color-gray-400);
}

.regions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.region-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  transition: all 0.3s ease;
}

.region-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(var(--color-primary-rgb), 0.3);
}

.region-info {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}

.region-number {
  background: rgba(var(--color-primary-rgb), 0.2);
  color: var(--color-primary);
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 0.85rem;
}

.region-times {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.9rem;
}

.time-label {
  color: var(--color-gray-300);
}

.time-value {
  color: var(--color-white);
  font-weight: 500;
  font-family: 'Courier New', monospace;
}

.separator {
  color: var(--color-gray-400);
}

.region-duration {
  color: var(--color-primary);
  font-weight: 600;
  margin-left: auto;
}

.region-actions {
  display: flex;
  gap: 8px;
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
  cursor: pointer;
  transition: all 0.2s ease;
  padding: 0;
  pointer-events: auto;
  z-index: 10;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.play-btn {
  color: var(--color-success-alt);
}

.play-btn:hover {
  border-color: rgba(var(--color-success-alt-rgb), 0.5);
  background: rgba(var(--color-success-alt-rgb), 0.1);
}

.delete-btn {
  color: var(--color-danger);
}

.delete-btn:hover {
  border-color: rgba(var(--color-danger-rgb), 0.5);
  background: rgba(var(--color-danger-rgb), 0.1);
}

.regions-list::-webkit-scrollbar {
  width: 6px;
}

.regions-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
}

.regions-list::-webkit-scrollbar-thumb {
  background: rgba(var(--color-primary-rgb), 0.5);
  border-radius: 3px;
}

.regions-list::-webkit-scrollbar-thumb:hover {
  background: rgba(var(--color-primary-rgb), 0.7);
}
</style>
