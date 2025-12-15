<template>
  <div
    class="timeline-playhead"
    :style="playheadStyle"
    @mousedown="startDrag"
  >
    <div class="playhead-line"></div>
    <div class="playhead-handle"></div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  currentTime: {
    type: Number,
    required: true
  },
  zoom: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['seek'])

const isDragging = ref(false)

const playheadStyle = computed(() => ({
  left: props.currentTime * props.zoom + 'px'
}))

function startDrag(event) {
  isDragging.value = true
  event.preventDefault()

  const onMouseMove = (e) => {
    if (!isDragging.value) return

    const timelineContent = e.target.closest('.timeline-content')
    if (!timelineContent) return

    const rect = timelineContent.getBoundingClientRect()
    const x = e.clientX - rect.left + timelineContent.scrollLeft
    const newTime = Math.max(0, x / props.zoom)

    emit('seek', newTime)
  }

  const onMouseUp = () => {
    isDragging.value = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  }

  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
}
</script>

<style scoped>
.timeline-playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 10;
  pointer-events: none;
}

.playhead-line {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 2px;
  background: #FF6B35;
  box-shadow: 0 0 8px rgba(255, 107, 53, 0.6);
}

.playhead-handle {
  position: absolute;
  top: 0;
  left: -6px;
  width: 14px;
  height: 14px;
  background: #FF6B35;
  border-radius: 50%;
  cursor: ew-resize;
  pointer-events: all;
  box-shadow: 0 0 8px rgba(255, 107, 53, 0.6);
  transition: transform 0.2s ease;
}

.playhead-handle:hover {
  transform: scale(1.2);
}
</style>
