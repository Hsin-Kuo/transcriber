<template>
  <div class="timeline-editor electric-card">
    <div class="electric-inner">
      <div class="electric-border-outer">
        <div class="electric-main timeline-container">
          <!-- Control Bar -->
          <div class="timeline-controls">
            <div class="control-buttons">
              <button
                @click="togglePlay"
                class="control-btn"
                :class="{ active: isPlaying }"
              >
                <svg v-if="!isPlaying" width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <polygon points="5 3 19 12 5 21 5 3"></polygon>
                </svg>
                <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="4" width="4" height="16"></rect>
                  <rect x="14" y="4" width="4" height="16"></rect>
                </svg>
                <span>{{ isPlaying ? '暫停' : '播放' }}</span>
              </button>

              <button @click="stop" class="control-btn">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="6" width="12" height="12"></rect>
                </svg>
                <span>停止</span>
              </button>
            </div>

            <div class="zoom-control">
              <span>縮放:</span>
              <input
                type="range"
                v-model="zoom"
                min="20"
                max="200"
                step="10"
                class="zoom-slider"
              />
              <span class="zoom-value">{{ zoom }}px/s</span>
            </div>

            <div class="time-display">
              <span>{{ formatTime(currentTime) }} / {{ formatTime(totalDuration) }}</span>
            </div>
          </div>

          <!-- Timeline Content -->
          <div class="timeline-content" ref="timelineContentRef">
            <!-- Ruler -->
            <TimelineRuler :zoom="zoom" :duration="totalDuration" />

            <!-- Playhead -->
            <TimelinePlayhead
              :current-time="currentTime"
              :zoom="zoom"
              @seek="handleSeek"
            />

            <!-- Tracks -->
            <div class="timeline-tracks">
              <TimelineTrack
                v-for="track in timeline.tracks"
                :key="track.id"
                :track="track"
                :zoom="zoom"
                @clips-reordered="handleClipsReordered"
                @clip-deleted="handleClipDeleted"
              />
            </div>

            <!-- Add Track Button -->
            <div class="add-track-section">
              <button @click="addTrack" class="add-track-btn">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="12" y1="5" x2="12" y2="19"></line>
                  <line x1="5" y1="12" x2="19" y2="12"></line>
                </svg>
                新增軌道
              </button>
            </div>
          </div>

          <!-- Export Button -->
          <div class="timeline-footer">
            <button @click="exportTimeline" class="export-btn" :disabled="!hasClips">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              匯出時間軸為音檔
            </button>
          </div>
        </div>
      </div>
      <div class="electric-glow-1"></div>
      <div class="electric-glow-2"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import TimelineRuler from './TimelineRuler.vue'
import TimelinePlayhead from './TimelinePlayhead.vue'
import TimelineTrack from './TimelineTrack.vue'

const props = defineProps({
  clips: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['timeline-export'])

// Timeline state
const timeline = ref({
  tracks: [
    { id: 'track-1', name: 'Track 1', clips: [] }
  ]
})

const zoom = ref(50) // px per second
const currentTime = ref(0)
const isPlaying = ref(false)
const timelineContentRef = ref(null)

// Computed properties
const totalDuration = computed(() => {
  let maxEnd = 0
  timeline.value.tracks.forEach(track => {
    track.clips.forEach(clip => {
      const end = clip.position + clip.duration
      if (end > maxEnd) maxEnd = end
    })
  })
  return maxEnd || 0
})

const hasClips = computed(() => {
  return timeline.value.tracks.some(track => track.clips.length > 0)
})

// Watch for clip changes from parent
watch(() => props.clips, (newClips) => {
  syncClipsToTimeline(newClips)
}, { immediate: true, deep: true })

// Functions
function syncClipsToTimeline(clips) {
  if (!clips || clips.length === 0) return

  let position = 0
  const timelineClips = clips.map((clip, index) => {
    const timelineClip = {
      id: `timeline-${clip.id}`,
      clipId: clip.id,
      name: clip.name || `Clip ${index + 1}`,
      position: position,
      duration: clip.duration || 0,
      volume: 0,
      fadeIn: 0,
      fadeOut: 0,
      waveformCache: null
    }
    position += (clip.duration || 0) + 0.1 // 0.1s gap between clips
    return timelineClip
  })

  // Update first track with clips
  if (timeline.value.tracks.length > 0) {
    timeline.value.tracks[0].clips = timelineClips
  }
}

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

function togglePlay() {
  isPlaying.value = !isPlaying.value
  // TODO: Implement actual playback in Stage 2
}

function stop() {
  isPlaying.value = false
  currentTime.value = 0
}

function handleSeek(time) {
  currentTime.value = time
}

function handleClipsReordered(trackId, reorderedClips) {
  const track = timeline.value.tracks.find(t => t.id === trackId)
  if (track) {
    // Recalculate positions after reordering
    let position = 0
    reorderedClips.forEach(clip => {
      clip.position = position
      position += clip.duration + 0.1
    })
    track.clips = reorderedClips
  }
}

function handleClipDeleted(trackId, clipId) {
  const track = timeline.value.tracks.find(t => t.id === trackId)
  if (track) {
    track.clips = track.clips.filter(c => c.id !== clipId)
    // Recalculate positions
    let position = 0
    track.clips.forEach(clip => {
      clip.position = position
      position += clip.duration + 0.1
    })
  }
}

function addTrack() {
  const newTrackId = `track-${timeline.value.tracks.length + 1}`
  timeline.value.tracks.push({
    id: newTrackId,
    name: `Track ${timeline.value.tracks.length + 1}`,
    clips: []
  })
}

function exportTimeline() {
  if (!hasClips.value) return

  // Prepare timeline data for export
  const exportData = {
    tracks: timeline.value.tracks.map(track => ({
      id: track.id,
      name: track.name,
      clips: track.clips.map(clip => ({
        clipId: clip.clipId,
        position: clip.position,
        duration: clip.duration,
        volume: clip.volume,
        fadeIn: clip.fadeIn,
        fadeOut: clip.fadeOut
      }))
    })),
    options: {
      crossfade: 0.1,
      normalize: true,
      silence_gap: 0.05
    }
  }

  emit('timeline-export', exportData)
}
</script>

<style scoped>
.timeline-editor {
  margin-top: 24px;
}

.timeline-container {
  background: linear-gradient(135deg, rgba(28, 28, 28, 0.95) 0%, rgba(20, 20, 20, 0.95) 100%);
  border-radius: 12px;
  padding: 20px;
}

.timeline-controls {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.control-buttons {
  display: flex;
  gap: 8px;
}

.control-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: rgba(255, 107, 53, 0.1);
  border: 1px solid rgba(255, 107, 53, 0.3);
  border-radius: 6px;
  color: var(--color-orange);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.control-btn:hover {
  background: rgba(255, 107, 53, 0.2);
  border-color: rgba(255, 107, 53, 0.5);
}

.control-btn.active {
  background: rgba(221, 132, 72, 0.2);
  border-color: rgba(221, 132, 72, 0.5);
  color: var(--color-primary);
}

.control-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.zoom-control {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--color-gray-200);
  font-size: 14px;
}

.zoom-slider {
  width: 150px;
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  outline: none;
  -webkit-appearance: none;
}

.zoom-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  background: var(--color-orange);
  border-radius: 50%;
  cursor: pointer;
}

.zoom-slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  background: var(--color-orange);
  border-radius: 50%;
  cursor: pointer;
  border: none;
}

.zoom-value {
  min-width: 60px;
  text-align: right;
  font-weight: 500;
  color: var(--color-orange);
}

.time-display {
  margin-left: auto;
  color: var(--color-gray-200);
  font-size: 14px;
  font-weight: 500;
  font-family: monospace;
}

.timeline-content {
  position: relative;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  overflow-x: auto;
  overflow-y: visible;
  min-height: 200px;
}

.timeline-tracks {
  position: relative;
  min-height: 100px;
}

.add-track-section {
  padding: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.add-track-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px dashed rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  color: var(--color-gray-200);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
  width: 100%;
  justify-content: center;
}

.add-track-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.3);
  color: var(--color-white);
}

.timeline-footer {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  justify-content: flex-end;
}

.export-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: linear-gradient(135deg, var(--color-orange) 0%, var(--color-primary) 100%);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 12px rgba(255, 107, 53, 0.3);
}

.export-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(255, 107, 53, 0.4);
}

.export-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 768px) {
  .timeline-controls {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .zoom-control {
    justify-content: space-between;
  }

  .time-display {
    margin-left: 0;
    text-align: center;
  }
}
</style>
