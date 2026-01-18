<template>
  <div class="merge-action-panel">
    <div class="action-description">
      <p>即將合併 {{ files.length }} 個音檔</p>
      <p class="hint">請選擇操作：</p>
    </div>

    <div class="action-buttons">
      <button
        class="btn btn-primary"
        :disabled="merging"
        @click="$emit('start-transcription')"
      >
        <svg v-if="!merging" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
        <span class="spinner" v-if="merging"></span>
        {{ merging ? '合併中...' : '進入轉錄設定' }}
      </button>

      <button
        class="btn btn-secondary"
        :disabled="merging"
        @click="$emit('download-merged')"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="7 10 12 15 17 10"></polyline>
          <line x1="12" y1="15" x2="12" y2="3"></line>
        </svg>
        下載合併音檔
      </button>

      <button
        class="btn btn-cancel"
        :disabled="merging"
        @click="$emit('cancel')"
      >
        取消
      </button>
    </div>

    <div v-if="merging" class="merging-progress">
      <div class="progress-bar">
        <div class="progress-fill"></div>
      </div>
      <p>正在合併音檔，請稍候...</p>
    </div>
  </div>
</template>

<script setup>
defineProps({
  files: {
    type: Array,
    required: true
  },
  merging: {
    type: Boolean,
    default: false
  }
})

defineEmits(['start-transcription', 'download-merged', 'cancel'])
</script>

<style scoped>
.merge-action-panel {
  width: 100%;
  max-width: 700px;
  margin: 20px auto;
  padding: 24px;
  background: var(--neu-bg);
  border-radius: 16px;
  box-shadow: var(--neu-shadow-raised);
}

.action-description {
  text-align: center;
  margin-bottom: 20px;
}

.action-description p {
  margin: 0;
  font-size: 15px;
  color: rgba(var(--color-text-dark-rgb), 0.9);
  font-weight: 500;
}

.action-description .hint {
  margin-top: 8px;
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  font-weight: 400;
}

.action-buttons {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 24px;
  font-size: 15px;
  font-weight: 600;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s;
  width: 100%;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--neu-bg);
  color: var(--neu-primary);
  box-shadow: var(--neu-shadow-btn);
}

.btn-primary:hover:not(:disabled) {
  box-shadow: var(--neu-shadow-btn-hover);
  color: var(--neu-primary-dark);
  transform: translateY(-1px);
}

.btn-primary:active:not(:disabled) {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateY(0);
}

.btn-secondary {
  background: var(--color-teal);
  color: white;
}

.btn-secondary:hover:not(:disabled) {
  background: var(--color-teal-dark);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(var(--color-teal-rgb), 0.3);
}

.btn-cancel {
  padding: 10px 20px;
  font-size: 13px;
  background: transparent;
  color: rgba(var(--color-text-dark-rgb), 0.6);
  border: 1px solid rgba(var(--color-text-dark-rgb), 0.2);
}

.btn-cancel:hover:not(:disabled) {
  background: rgba(var(--color-danger-rgb), 0.1);
  color: var(--color-danger);
  border-color: var(--color-danger);
}

.merging-progress {
  text-align: center;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(221, 132, 72, 0.2);
}

.progress-bar {
  width: 100%;
  height: 4px;
  background: rgba(221, 132, 72, 0.2);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 12px;
}

.progress-fill {
  height: 100%;
  background: var(--electric-primary);
  animation: progress 2s ease-in-out infinite;
}

@keyframes progress {
  0% {
    width: 0%;
    margin-left: 0%;
  }
  50% {
    width: 50%;
    margin-left: 25%;
  }
  100% {
    width: 0%;
    margin-left: 100%;
  }
}

.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.merging-progress p {
  font-size: 13px;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  margin: 0;
}

@media (max-width: 768px) {
  .merge-action-panel {
    padding: 20px;
  }

  .btn {
    padding: 12px 20px;
    font-size: 14px;
  }
}
</style>
