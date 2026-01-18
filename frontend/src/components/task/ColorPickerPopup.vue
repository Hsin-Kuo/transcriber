<template>
  <div v-if="isOpen">
    <!-- 遮罩層 -->
    <div
      class="color-picker-overlay"
      @click="close"
    ></div>

    <!-- 顏色選擇器彈窗 -->
    <div
      class="color-picker-popup"
      :style="position"
      @click.stop
    >
      <div class="color-picker-header">
        <span>{{ $t('taskList.selectColor') }}</span>
        <button class="btn-close-picker" @click="close">✕</button>
      </div>

      <!-- 顏色輸入框 -->
      <input
        type="color"
        :value="currentColor"
        @input="handleColorInput"
        class="color-input"
      />

      <!-- 預設顏色網格 -->
      <div class="preset-colors">
        <button
          v-for="color in presetColors"
          :key="color"
          class="preset-color-btn"
          :style="{ backgroundColor: color }"
          @click="selectColor(color)"
          :title="color"
        ></button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { presetColors } from '../../composables/task/useTaskTags'

const { t: $t } = useI18n()

// Props
const props = defineProps({
  isOpen: {
    type: Boolean,
    required: true
  },
  currentColor: {
    type: String,
    required: true
  },
  position: {
    type: Object,
    default: () => ({})
  },
  targetTag: {
    type: String,
    default: ''
  }
})

// Emits
const emit = defineEmits(['update:isOpen', 'color-selected'])

// Methods
function close() {
  emit('update:isOpen', false)
}

function handleColorInput(event) {
  selectColor(event.target.value)
}

function selectColor(color) {
  emit('color-selected', {
    tag: props.targetTag,
    color
  })
  // 不自動關閉，讓使用者可以連續調整
}
</script>

<style scoped>
/* 遮罩層 */
.color-picker-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.1);
  z-index: 9998;
  cursor: default;
}

/* 彈窗主體 */
.color-picker-popup {
  position: fixed;
  background: white;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  z-index: 9999;
  min-width: 220px;
}

/* 標題列 */
.color-picker-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: rgba(var(--color-text-dark-rgb), 0.8);
}

/* 關閉按鈕 */
.btn-close-picker {
  width: 20px;
  height: 20px;
  padding: 0;
  background: rgba(var(--color-danger-rgb), 0.1);
  border: none;
  border-radius: 4px;
  color: var(--color-danger);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-close-picker:hover {
  background: rgba(var(--color-danger-rgb), 0.2);
}

/* 顏色輸入框 */
.color-input {
  width: 100%;
  height: 40px;
  border: 1px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 10px;
}

/* 預設顏色網格 */
.preset-colors {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
}

/* 預設顏色按鈕 */
.preset-color-btn {
  width: 32px;
  height: 32px;
  border: 2px solid rgba(255, 255, 255, 0.8);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.preset-color-btn:hover {
  transform: scale(1.1);
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.2);
  border-color: white;
}
</style>
