<script setup>
import { computed } from 'vue'

// 通用多選下拉：以原生 <details> 做開合（免 click-outside 處理），內含 checkbox。
// options 接受 string[] 或 {value,label}[]。v-model 為已選 value 的陣列。
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  options: { type: Array, default: () => [] },
  label: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const norm = computed(() =>
  props.options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o))
)
const selectedSet = computed(() => new Set(props.modelValue))
const allSelected = computed(
  () => norm.value.length > 0 && norm.value.every((o) => selectedSet.value.has(o.value))
)
const summaryText = computed(() => {
  if (norm.value.length === 0) return '—'
  if (props.modelValue.length === 0 || allSelected.value) return '全部'
  return `${props.modelValue.length} / ${norm.value.length}`
})

// 依 options 原順序回傳，維持穩定排序
function emitFromSet(set) {
  emit('update:modelValue', norm.value.map((o) => o.value).filter((v) => set.has(v)))
}
function toggle(value, checked) {
  const next = new Set(props.modelValue)
  if (checked) next.add(value)
  else next.delete(value)
  emitFromSet(next)
}
function selectAll() {
  emit('update:modelValue', norm.value.map((o) => o.value))
}
function clearAll() {
  emit('update:modelValue', [])
}
</script>

<template>
  <details class="ms">
    <summary class="ms-summary">{{ label }}：{{ summaryText }} ▾</summary>
    <div class="ms-panel">
      <div class="ms-actions">
        <button type="button" @click="selectAll">全選</button>
        <button type="button" @click="clearAll">清除</button>
      </div>
      <label v-for="o in norm" :key="o.value" class="ms-option">
        <input
          type="checkbox"
          :checked="selectedSet.has(o.value)"
          @change="toggle(o.value, $event.target.checked)"
        />
        <span>{{ o.label }}</span>
      </label>
      <div v-if="norm.length === 0" class="ms-empty">無選項</div>
    </div>
  </details>
</template>

<style scoped>
.ms {
  position: relative;
  display: inline-block;
}

.ms-summary {
  list-style: none;
  cursor: pointer;
  padding: 8px 12px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 8px;
  background: white;
  color: var(--color-text, rgb(145, 106, 45));
  font-size: 14px;
  white-space: nowrap;
  user-select: none;
}

.ms-summary::-webkit-details-marker {
  display: none;
}

.ms[open] .ms-summary {
  border-color: var(--color-primary, #dd8448);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.12);
}

.ms-panel {
  position: absolute;
  z-index: 30;
  top: calc(100% + 4px);
  left: 0;
  min-width: 180px;
  max-height: 280px;
  overflow-y: auto;
  background: white;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.12);
  padding: 8px;
}

.ms-actions {
  display: flex;
  gap: 8px;
  padding: 4px 4px 8px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.15);
  margin-bottom: 6px;
}

.ms-actions button {
  flex: 1;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 6px;
  background: #fafafa;
  color: var(--color-text, rgb(145, 106, 45));
  cursor: pointer;
}

.ms-actions button:hover {
  background: #fff8f3;
  border-color: var(--color-primary, #dd8448);
}

.ms-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 4px;
  font-size: 13px;
  color: var(--color-text, rgb(145, 106, 45));
  cursor: pointer;
  white-space: nowrap;
}

.ms-option:hover {
  background: rgba(221, 132, 72, 0.06);
  border-radius: 4px;
}

.ms-option input {
  cursor: pointer;
}

.ms-empty {
  padding: 8px 4px;
  font-size: 12px;
  color: var(--color-text-light, #a0917c);
}
</style>
