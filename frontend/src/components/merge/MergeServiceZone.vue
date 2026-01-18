<template>
  <div class="merge-service-zone">
    <button
      class="merge-btn"
      @click="openModal"
      :disabled="disabled"
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M8 6h13"></path>
        <path d="M8 12h13"></path>
        <path d="M8 18h13"></path>
        <path d="M3 6h.01"></path>
        <path d="M3 12h.01"></path>
        <path d="M3 18h.01"></path>
      </svg>
      <span>合併音檔</span>
    </button>

    <!-- 合併對話窗 -->
    <MergeModal
      :visible="showModal"
      @close="closeModal"
      @confirm="handleConfirm"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import MergeModal from './MergeModal.vue'

defineProps({
  disabled: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['show-transcription-form'])

const showModal = ref(false)

function openModal() {
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

function handleConfirm(files) {
  showModal.value = false
  emit('show-transcription-form', files)
}
</script>

<style scoped>
.merge-service-zone {
  width: 100%;
  max-width: 800px;
  margin: 16px auto 0;
}

.merge-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 14px 24px;
  font-size: 15px;
  font-weight: 500;
  color: rgba(var(--color-text-dark-rgb), 0.7);
  background: var(--neu-bg, #e0e5ec);
  border: 2px dashed rgba(var(--color-divider-rgb), 0.4);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.3s;
}

.merge-btn:hover:not(:disabled) {
  color: var(--electric-primary, #dd8448);
  border-color: rgba(221, 132, 72, 0.4);
  background: rgba(221, 132, 72, 0.05);
}

.merge-btn:hover:not(:disabled) svg {
  color: var(--electric-primary, #dd8448);
}

.merge-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.merge-btn svg {
  color: rgba(var(--color-text-dark-rgb), 0.5);
  transition: color 0.3s;
}

@media (max-width: 768px) {
  .merge-service-zone {
    margin-top: 12px;
  }

  .merge-btn {
    padding: 12px 20px;
    font-size: 14px;
  }
}
</style>
