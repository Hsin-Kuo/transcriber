<template>
  <Teleport to="body">
    <Transition name="bs">
      <div v-if="modelValue" class="bottom-sheet-overlay" @click.self="close">
        <div ref="sheetRef" class="bottom-sheet" @click.stop role="dialog" aria-modal="true" :aria-label="title">
          <div class="bottom-sheet-handle"></div>
          <div v-if="title" class="bottom-sheet-header">
            <span>{{ title }}</span>
            <button class="bottom-sheet-close" @click="close" :aria-label="$t('common.close')">✕</button>
          </div>
          <div class="bottom-sheet-content">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, toRef } from 'vue'
import { useFocusTrap } from '../../composables/useFocusTrap'

const props = defineProps({
  modelValue: { type: Boolean, required: true },
  title: { type: String, default: '' }
})

const emit = defineEmits(['update:modelValue'])

const sheetRef = ref(null)
useFocusTrap(sheetRef, toRef(props, 'modelValue'))

function close() {
  emit('update:modelValue', false)
}
</script>

<style scoped>
.bottom-sheet-overlay {
  position: fixed;
  inset: 0;
  background: var(--color-overlay);
  z-index: 1050;
  display: flex;
  align-items: flex-end;
}

.bottom-sheet {
  width: 100%;
  max-height: 80vh;
  background: var(--upload-bg);
  border-radius: 20px 20px 0 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.bottom-sheet-handle {
  width: 40px;
  height: 4px;
  background: rgba(var(--color-divider-rgb), 0.4);
  border-radius: 2px;
  margin: 12px auto 0;
  flex-shrink: 0;
}

.bottom-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px 10px;
  font-size: 15px;
  font-weight: 600;
  color: var(--main-text);
  flex-shrink: 0;
  border-bottom: 1px solid rgba(var(--color-divider-rgb), 0.3);
}

.bottom-sheet-close {
  background: transparent;
  border: none;
  font-size: 16px;
  cursor: pointer;
  color: var(--color-text-muted);
  padding: 4px;
  line-height: 1;
}

.bottom-sheet-content {
  overflow-y: auto;
  padding: 16px 20px 32px;
  flex: 1;
}

/* Transition */
.bs-enter-active {
  transition: opacity 0.25s ease;
}
.bs-leave-active {
  transition: opacity 0.2s ease;
}
.bs-enter-from,
.bs-leave-to {
  opacity: 0;
}

.bs-enter-active .bottom-sheet {
  animation: sheet-slide-up 0.3s ease forwards;
}
.bs-leave-active .bottom-sheet {
  animation: sheet-slide-down 0.2s ease forwards;
}

@keyframes sheet-slide-up {
  from { transform: translateY(100%); }
  to   { transform: translateY(0); }
}
@keyframes sheet-slide-down {
  from { transform: translateY(0); }
  to   { transform: translateY(100%); }
}
</style>
