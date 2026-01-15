<template>
  <div
    class="timeline-clip"
    :style="clipStyle"
    :title="clip.name"
  >
    <div class="clip-content">
      <!-- Waveform or Icon -->
      <div v-if="showWaveform" class="clip-waveform" ref="waveformRef">
        <!-- Waveform will be rendered here in Stage 3 -->
      </div>
      <div v-else class="clip-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 18V5l12-2v13"></path>
          <circle cx="6" cy="18" r="3"></circle>
          <circle cx="18" cy="16" r="3"></circle>
        </svg>
      </div>

      <!-- Clip Info -->
      <div class="clip-info">
        <div class="clip-name">{{ clipName }}</div>
        <div class="clip-duration">{{ formatDuration(clip.duration) }}</div>
      </div>

      <!-- Delete Button -->
      <button
        class="clip-delete"
        @click.stop="handleDelete"
        title="刪除片段"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  clip: {
    type: Object,
    required: true
  },
  zoom: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['delete'])

const waveformRef = ref(null)

const clipStyle = computed(() => {
  const width = Math.max(props.clip.duration * props.zoom, 80) // Min width 80px
  return {
    width: width + 'px',
    minWidth: '80px'
  }
})

const clipName = computed(() => {
  const name = props.clip.name || 'Untitled'
  // Truncate long names
  return name.length > 20 ? name.substring(0, 17) + '...' : name
})

const showWaveform = computed(() => {
  // Only show waveform for clips < 30s (will be implemented in Stage 3)
  return props.clip.duration < 30 && props.clip.waveformCache
})

function formatDuration(seconds) {
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`
  }
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function handleDelete() {
  if (confirm(`確定要刪除片段「${props.clip.name}」嗎？`)) {
    emit('delete', props.clip.id)
  }
}
</script>

<style scoped>
.timeline-clip {
  position: relative;
  height: 60px;
  background: linear-gradient(135deg, rgba(255, 107, 53, 0.2) 0%, rgba(221, 132, 72, 0.2) 100%);
  border: 2px solid rgba(255, 107, 53, 0.4);
  border-radius: 6px;
  cursor: inherit;
  transition: all 0.2s ease;
  overflow: hidden;
}

.timeline-clip:hover {
  border-color: rgba(255, 107, 53, 0.6);
  box-shadow: 0 4px 12px rgba(255, 107, 53, 0.3);
  transform: translateY(-2px);
}

.timeline-clip:active {
  cursor: grabbing;
}

.clip-content {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  padding: 8px 12px;
  gap: 8px;
}

.clip-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 107, 53, 0.2);
  border-radius: 4px;
  color: #FF6B35;
}

.clip-waveform {
  flex: 1;
  height: 40px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
}

.clip-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.clip-name {
  font-size: 13px;
  font-weight: 500;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.clip-duration {
  font-size: 11px;
  color: #aaa;
  font-family: monospace;
}

.clip-delete {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 0, 0, 0.2);
  border: 1px solid rgba(255, 0, 0, 0.3);
  border-radius: 4px;
  color: #ff5555;
  cursor: pointer;
  opacity: 0;
  transition: all 0.2s ease;
  padding: 0;
  pointer-events: auto;
}

.timeline-clip:hover .clip-delete {
  opacity: 1;
}

.clip-delete:hover {
  background: rgba(255, 0, 0, 0.3);
  border-color: rgba(255, 0, 0, 0.5);
  color: #ff3333;
}
</style>
