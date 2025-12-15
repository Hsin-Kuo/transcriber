<template>
  <div class="timeline-track">
    <div class="track-header">
      <span class="track-name">{{ track.name }}</span>
      <span class="track-info">{{ track.clips.length }} 個片段</span>
    </div>
    <div class="track-content">
      <draggable
        v-model="trackClips"
        @end="onDragEnd"
        item-key="id"
        class="clips-container"
        :animation="200"
        ghost-class="clip-ghost"
        chosen-class="clip-chosen"
      >
        <template #item="{ element }">
          <TimelineClip
            :clip="element"
            :zoom="zoom"
            @delete="handleClipDelete"
          />
        </template>
      </draggable>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { VueDraggableNext as draggable } from 'vue-draggable-next'
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

// Watch for external changes to track clips
watch(
  () => props.track.clips,
  (newClips) => {
    trackClips.value = [...newClips]
  },
  { deep: true }
)

function onDragEnd() {
  // Recalculate positions after drag
  let position = 0
  trackClips.value.forEach(clip => {
    clip.position = position
    position += clip.duration + 0.1 // 0.1s gap
  })

  emit('clips-reordered', props.track.id, trackClips.value)
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
}

.clip-ghost {
  opacity: 0.5;
  background: rgba(255, 107, 53, 0.3);
}

.clip-chosen {
  opacity: 0.8;
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
