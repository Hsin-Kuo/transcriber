<template>
  <div class="clip-manager electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main manager-content">
          <div class="manager-header">
            <h3>🎬 已剪輯片段</h3>
            <span class="clip-count">{{ clips.length }} 個片段</span>
          </div>

          <div v-if="clips.length === 0" class="empty-state">
            <p>尚無剪輯片段</p>
            <p class="hint">選取區段後點擊「剪輯選取區段」按鈕</p>
          </div>

          <div v-else class="clips-list">
            <div
              v-for="clip in clips"
              :key="clip.id"
              class="clip-item"
            >
              <div class="clip-info">
                <span class="clip-icon">🎵</span>
                <div class="clip-details">
                  <div class="clip-name">{{ clip.name }}</div>
                  <div class="clip-meta">
                    <span class="clip-source">{{ clip.source }}</span>
                    <span class="clip-duration">{{ formatDuration(clip.duration) }}</span>
                  </div>
                </div>
              </div>
              <div class="clip-actions">
                <a
                  :href="clip.url"
                  download
                  class="action-btn download-btn"
                  title="下載"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                  </svg>
                </a>
                <button
                  @click="$emit('clip-deleted', clip.id)"
                  class="action-btn delete-btn"
                  title="刪除"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
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
  clips: {
    type: Array,
    default: () => []
  }
})

defineEmits(['clip-deleted'])

function formatDuration(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}
</script>

<style scoped>
.manager-content {
  padding: 24px;
  background: linear-gradient(135deg, rgba(28, 28, 28, 0.95) 0%, rgba(20, 20, 20, 0.95) 100%);
}

.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.manager-header h3 {
  margin: 0;
  font-size: 1.3rem;
  color: #fff;
}

.clip-count {
  background: rgba(33, 150, 243, 0.2);
  color: #2196F3;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 600;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: #888;
}

.empty-state p {
  margin: 8px 0;
}

.hint {
  font-size: 0.9rem;
  color: #666;
}

.clips-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.clip-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  transition: all 0.3s ease;
}

.clip-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(33, 150, 243, 0.3);
}

.clip-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.clip-icon {
  font-size: 1.5rem;
}

.clip-details {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.clip-name {
  color: #fff;
  font-weight: 500;
  font-size: 1rem;
}

.clip-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.85rem;
}

.clip-source {
  color: #888;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.clip-duration {
  color: #2196F3;
  font-weight: 600;
  font-family: 'Courier New', monospace;
}

.clip-actions {
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
  text-decoration: none;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.download-btn {
  color: #4CAF50;
}

.download-btn:hover {
  border-color: rgba(76, 175, 80, 0.5);
  background: rgba(76, 175, 80, 0.1);
}

.delete-btn {
  color: #F44336;
}

.delete-btn:hover {
  border-color: rgba(244, 67, 54, 0.5);
  background: rgba(244, 67, 54, 0.1);
}

.clips-list::-webkit-scrollbar {
  width: 6px;
}

.clips-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 3px;
}

.clips-list::-webkit-scrollbar-thumb {
  background: rgba(33, 150, 243, 0.5);
  border-radius: 3px;
}

.clips-list::-webkit-scrollbar-thumb:hover {
  background: rgba(33, 150, 243, 0.7);
}
</style>
