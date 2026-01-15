<template>
  <div class="timeline-track">
    <div class="track-header">
      <span class="track-name">{{ track.name }}</span>
      <span class="track-info">{{ track.clips.length }} 個片段</span>
    </div>
    <div class="track-content">
      <div class="clips-container">
        <div
          v-for="(clip, index) in trackClips"
          :key="clip.id"
          :class="['clip-wrapper', {
            dragging: draggedIndex === index,
            'drag-over': dragOverIndex === index && draggedIndex !== index
          }]"
          :draggable="true"
          @dragstart="handleDragStart(index, $event)"
          @dragover.prevent="handleDragOver(index, $event)"
          @dragenter="handleDragEnter(index, $event)"
          @dragleave="handleDragLeave"
          @drop.prevent="handleDrop(index, $event)"
          @dragend="handleDragEnd"
        >
          <TimelineClip
            :clip="clip"
            :zoom="zoom"
            @delete="handleClipDelete"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import TimelineClip from './TimelineClip.vue'

const props = defineProps({
  track: {
    type: Object,
    required: true
  },
  zoom: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['clips-reordered', 'clip-deleted'])

const trackClips = ref([...props.track.clips])
const draggedIndex = ref(null)
const dragOverIndex = ref(null)

// Watch for external changes to track clips
watch(
  () => props.track.clips,
  (newClips) => {
    trackClips.value = [...newClips]
  },
  { deep: true }
)

function handleDragStart(index, event) {
  draggedIndex.value = index
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', index.toString())
  console.log('Drag start:', index)
}

function handleDragEnter(index, event) {
  if (draggedIndex.value !== null && draggedIndex.value !== index) {
    dragOverIndex.value = index
    console.log('Drag enter:', index)
  }
}

function handleDragLeave() {
  dragOverIndex.value = null
}

function handleDragOver(index, event) {
  if (draggedIndex.value !== null && draggedIndex.value !== index) {
    event.dataTransfer.dropEffect = 'move'
    console.log('Drag over:', index)
  }
}

function handleDrop(index, event) {
  console.log('🎯 DROP triggered! index:', index, 'from:', draggedIndex.value)

  if (draggedIndex.value === null) {
    console.log('No dragged index')
    return
  }

  if (draggedIndex.value === index) {
    console.log('Same index, no reorder needed')
    return
  }

  console.log('Reordering clips...')

  // 重新排序片段
  const items = [...trackClips.value]
  const draggedItem = items[draggedIndex.value]
  items.splice(draggedIndex.value, 1)
  items.splice(index, 0, draggedItem)

  trackClips.value = items

  // 重新計算位置
  let position = 0
  trackClips.value.forEach(clip => {
    clip.position = position
    position += clip.duration + 0.1 // 0.1s gap
  })

  console.log('✅ Clips reordered:', trackClips.value.map(c => c.name))
  emit('clips-reordered', props.track.id, trackClips.value)
}

function handleDragEnd() {
  console.log('Drag end')
  draggedIndex.value = null
  dragOverIndex.value = null
}

function handleClipDelete(clipId) {
  emit('clip-deleted', props.track.id, clipId)
}
</script>

<style scoped>
.timeline-track {
  display: flex;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  min-height: 80px;
}

.track-header {
  flex-shrink: 0;
  width: 150px;
  padding: 16px;
  background: rgba(0, 0, 0, 0.3);
  border-right: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.track-name {
  font-size: 14px;
  font-weight: 500;
  color: #fff;
}

.track-info {
  font-size: 12px;
  color: #888;
}

.track-content {
  flex: 1;
  position: relative;
  min-height: 60px;
  padding: 10px 0;
}

.clips-container {
  display: flex;
  gap: 8px;
  padding: 0 12px;
  align-items: center;
  min-height: 60px;
  user-select: none;
  cursor: default;
}

.clip-wrapper {
  transition: all 0.2s ease;
  position: relative;
  cursor: grab;
}

.clip-wrapper:active {
  cursor: grabbing;
}

.clip-wrapper.dragging {
  opacity: 0.4;
  transform: scale(0.95);
}

.clip-wrapper.drag-over {
  border-left: 3px solid #FF6B35;
  padding-left: 5px;
}

/* 正常狀態下，子元素可以交互 */
.clip-wrapper > * {
  pointer-events: auto;
}

/* 拖曳時禁用子元素的指針事件，確保拖放事件正確觸發 */
.clip-wrapper.dragging > * {
  pointer-events: none;
}

@media (max-width: 768px) {
  .track-header {
    width: 120px;
    padding: 12px;
  }

  .track-name {
    font-size: 13px;
  }

  .track-info {
    font-size: 11px;
  }
}
</style>
