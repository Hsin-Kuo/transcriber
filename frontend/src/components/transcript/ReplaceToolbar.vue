<template>
  <div class="replace-toolbar">
    <input
      :value="findText"
      @input="$emit('update:findText', $event.target.value)"
      type="text"
      :placeholder="$t('replaceToolbar.find')"
      class="replace-input"
      @keydown.enter="handleEnter"
      @compositionstart="isComposing = true"
      @compositionend="isComposing = false"
    />
    <input
      :value="replaceText"
      @input="$emit('update:replaceText', $event.target.value)"
      type="text"
      :placeholder="$t('replaceToolbar.replaceWith')"
      class="replace-input"
      @keydown.enter="handleEnter"
      @compositionstart="isComposing = true"
      @compositionend="isComposing = false"
    />
    <button
      class="btn btn-primary"
      @click="$emit('replace-all')"
      :disabled="!findText"
    >
      {{ $t('replaceToolbar.replaceAll') }}
    </button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  findText: {
    type: String,
    default: ''
  },
  replaceText: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:findText', 'update:replaceText', 'replace-all'])

// 追蹤輸入法狀態
const isComposing = ref(false)

// 處理 Enter 鍵
function handleEnter(event) {
  // 如果正在使用輸入法選字，不觸發取代
  if (isComposing.value) {
    return
  }

  // 否則阻止默認行為並觸發取代
  event.preventDefault()
  emit('replace-all')
}
</script>

<style scoped>
/* Replace toolbar */
.replace-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 20px;
  padding: 16px;
  background: rgba(163, 177, 198, 0.1);
  border-radius: 12px;
  align-items: stretch;
}

.replace-input {
  flex: 1;
  min-width: 150px;
  padding: 10px 14px;
  border: none;
  border-radius: 8px;
  background: var(--neu-bg);
  color: var(--neu-text);
  font-size: 0.95rem;
}

.replace-input:focus {
  outline: 2px solid var(--neu-primary);
}

@media (max-width: 768px) {
  .replace-toolbar {
    flex-direction: column;
  }
}
</style>
