<template>
  <!-- 中間省略檔名：頭段吃剩餘空間(超出由瀏覽器尾端省略)、尾段固定顯示末 N 字元(含副檔名)。
       純 CSS 寬度截斷 → 中英文/視窗寬度自動一致，不需量字元寬度。title 掛完整檔名。 -->
  <span class="truncated-filename" :title="name"
    ><span class="tf-head">{{ head }}</span
    ><span class="tf-tail">{{ tail }}</span
  ></span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, default: '' },
  // 尾段固定字元數（含副檔名）
  tailChars: { type: Number, default: 7 },
})

const tail = computed(() => {
  const n = props.name || ''
  return n.length > props.tailChars ? n.slice(-props.tailChars) : n
})

const head = computed(() => {
  const n = props.name || ''
  return n.length > props.tailChars ? n.slice(0, n.length - props.tailChars) : ''
})
</script>

<style scoped>
.truncated-filename {
  display: flex;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}

.tf-head {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tf-tail {
  flex: 0 0 auto;
  white-space: nowrap;
}
</style>
