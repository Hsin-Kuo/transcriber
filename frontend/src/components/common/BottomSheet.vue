<template>
  <Teleport to="body">
    <Transition name="bs">
      <div v-if="modelValue" class="bottom-sheet-overlay" @click.self="close">
        <div
          ref="sheetRef"
          class="bottom-sheet"
          :class="{ dragging }"
          :style="sheetStyle"
          @click.stop
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          @pointerdown="onPointerDown"
        >
          <div class="bottom-sheet-handle-zone">
            <div class="bottom-sheet-handle"></div>
          </div>
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
import { ref, computed, toRef } from 'vue'
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

// --- 向下拖曳關閉 ---
// 起手區限「把手 + 標題列」：內容區有自己的捲動，混用會和 native scroll 打架。
// 放手時位移 > 門檻（sheet 高度 25%，至少 80px）或往下甩（速度夠快）→ 關閉；
// 否則回彈。關閉時把當前位移寫進 CSS 變數，讓 leave 動畫從原地接續、不跳回頂部。
const dragY = ref(0)
const dragging = ref(false)
let startY = 0
let lastY = 0
let lastT = 0
let velocity = 0

const sheetStyle = computed(() => ({
  transform: dragY.value > 0 ? `translateY(${dragY.value}px)` : undefined,
  '--sheet-from': `${dragY.value}px`
}))

function onPointerDown(event) {
  if (!event.target.closest('.bottom-sheet-handle-zone, .bottom-sheet-header')) return
  if (event.target.closest('.bottom-sheet-close')) return
  dragging.value = true
  startY = event.clientY
  lastY = event.clientY
  lastT = event.timeStamp
  velocity = 0
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerUp)
}

function onPointerMove(event) {
  const dy = event.clientY - startY
  const dt = event.timeStamp - lastT
  if (dt > 0) velocity = (event.clientY - lastY) / dt
  lastY = event.clientY
  lastT = event.timeStamp
  // 只允許往下；往上給 0（sheet 已是全開狀態）
  dragY.value = Math.max(0, dy)
}

function onPointerUp() {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
  dragging.value = false
  const sheetH = sheetRef.value?.offsetHeight || 400
  const threshold = Math.max(80, sheetH * 0.25)
  if (dragY.value > threshold || velocity > 0.5) {
    close()
    // dragY 保留到 leave 動畫讀完 --sheet-from；下次開啟前歸零
    setTimeout(() => { dragY.value = 0 }, 250)
  } else {
    dragY.value = 0
  }
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
  transition: transform 0.25s ease;
}

.bottom-sheet.dragging {
  transition: none;
}

/* 把手擴大觸控區（視覺上仍是細條） */
.bottom-sheet-handle-zone {
  padding: 12px 0 4px;
  flex-shrink: 0;
  cursor: grab;
  touch-action: none;
}

.bottom-sheet-handle {
  width: 40px;
  height: 4px;
  background: rgba(var(--color-divider-rgb), 0.4);
  border-radius: 2px;
  margin: 0 auto;
}

.bottom-sheet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 20px 10px;
  font-size: 15px;
  font-weight: 600;
  color: var(--main-text);
  flex-shrink: 0;
  border-bottom: 1px solid rgba(var(--color-divider-rgb), 0.3);
  touch-action: none;
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
  /* 拖曳關閉時從放手位置接續下滑（--sheet-from 由 script 寫入，預設 0） */
  from { transform: translateY(var(--sheet-from, 0px)); }
  to   { transform: translateY(100%); }
}
</style>
