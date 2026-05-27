<template>
  <div class="audio-player-container">
    <audio
      v-if="hasAudioElement"
      v-show="audioUrl"
      ref="internalAudioElement"
      preload="metadata"
      :src="audioUrl || ''"
      @error="$emit('audio-error', $event)"
      @loadedmetadata="$emit('audio-loaded')"
      @canplay="$emit('update-duration')"
      @play="$emit('update:isPlaying', true)"
      @pause="$emit('update:isPlaying', false)"
      @ended="$emit('update:isPlaying', false)"
      @timeupdate="$emit('update-progress')"
      @durationchange="$emit('update-duration')"
      @volumechange="$emit('update-volume')"
      @ratechange="$emit('update-playback-rate')"
    >
      {{ $t('audioPlayer.browserNotSupported') }}
    </audio>

    <div v-if="audioError" class="audio-error">
      <div class="error-message">⚠️ {{ audioError }}</div>
      <button @click="$emit('reload-audio')" class="btn-retry">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
          <path d="M21 3v5h-5" />
          <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
          <path d="M3 21v-5h5" />
        </svg>
        {{ $t('audioPlayer.retryLoad') }}
      </button>
    </div>

    <div class="custom-audio-player circular-player">
      <!-- Circular progress bar (1/3 arc at top) -->
      <div class="circular-progress-container">
        <svg
          ref="svgElement"
          class="progress-arc"
          viewBox="0 0 200 140"
          @mousedown="startDragArc"
          @mousemove="dragArc"
          @mouseup="stopDragArc"
          @mouseleave="stopDragArc"
        >
          <!-- Hidden reference arc for drag calculation -->
          <path
            ref="arcReference"
            :d="arcReferencePath"
            fill="none"
            stroke="transparent"
            stroke-width="20"
            pointer-events="none"
          />

          <!-- Tick marks -->
          <g v-for="tick in tickMarks" :key="tick.index">
            <line
              :x1="tick.x1"
              :y1="tick.y1"
              :x2="tick.x2"
              :y2="tick.y2"
              :class="['tick-mark', { 'tick-active': tick.progress <= displayProgress }]"
              stroke-width="0.5"
              stroke-linecap="round"
            />
          </g>
        </svg>
      </div>

      <!-- Time display -->
      <div class="time-display-center">
        {{ formatTime(displayTime) }} / {{ formatTime(duration) }}
      </div>

      <!-- Central control area -->
      <div class="circular-controls-center">
        <!-- Rewind button -->
        <button class="audio-control-btn audio-skip-btn skip-backward" @click="$emit('skip-backward')" :title="$t('audioPlayer.rewind10s')" :aria-label="$t('audioPlayer.rewind10s')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          <span class="audio-control-label">10</span>
        </button>

        <!-- Play/Pause button -->
        <button class="audio-control-btn audio-play-btn" @click="$emit('toggle-play-pause')" :title="isPlaying ? $t('audioPlayer.pause') : $t('audioPlayer.play')" :aria-label="isPlaying ? $t('audioPlayer.pause') : $t('audioPlayer.play')">
          <svg v-if="!isPlaying" width="30" height="30" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5v14l11-7z" />
          </svg>
          <svg v-else width="30" height="30" viewBox="0 0 24 24" fill="currentColor">
            <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
          </svg>
        </button>

        <!-- Fast forward button -->
        <button class="audio-control-btn audio-skip-btn skip-forward" @click="$emit('skip-forward')" :title="$t('audioPlayer.fastForward10s')" :aria-label="$t('audioPlayer.fastForward10s')">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
            <path d="M21 3v5h-5" />
          </svg>
          <span class="audio-control-label">10</span>
        </button>
      </div>

      <!-- Volume and controls -->
      <div class="volume-and-controls">
        <!-- Left: Keyboard shortcuts info -->
        <KeyboardShortcutsInfo class="info-btn-wrapper" pop-direction="pop-up" />

        <!-- Middle: Volume control -->
        <div class="volume-control-center">
          <button class="audio-control-btn mute-btn-volume" @click="$emit('toggle-mute')" :title="isMuted ? $t('audioPlayer.unmute') : $t('audioPlayer.mute')" :aria-label="isMuted ? $t('audioPlayer.unmute') : $t('audioPlayer.mute')">
            <svg v-if="!isMuted && volume > 0.5" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z" />
            </svg>
            <svg v-else-if="!isMuted && volume > 0" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z" />
            </svg>
            <svg v-else width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z" />
            </svg>
          </button>

          <input
            type="range"
            class="volume-slider-horizontal"
            min="0"
            max="100"
            :value="volume * 100"
            :aria-label="$t('audioPlayer.volume')"
            :aria-valuenow="Math.round(volume * 100)"
            @input="$emit('set-volume', $event)"
          />
        </div>

        <!-- Right: Playback speed -->
        <PlaybackSpeedControl
          class="speed-btn-wrapper"
          :playback-rate="playbackRate"
          pop-direction="pop-up"
          @set-playback-rate="$emit('set-playback-rate', $event)"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatTime } from '../../utils/formatTime'
import KeyboardShortcutsInfo from './KeyboardShortcutsInfo.vue'
import PlaybackSpeedControl from './PlaybackSpeedControl.vue'

const { t: $t } = useI18n()

const props = defineProps({
  audioUrl: String,
  audioError: String,
  isPlaying: Boolean,
  volume: Number,
  isMuted: Boolean,
  playbackRate: Number,
  progressPercent: Number,
  duration: Number,
  displayTime: Number,
  hasAudioElement: { type: Boolean, default: false },
})

const emit = defineEmits([
  'update:isPlaying',
  'reload-audio',
  'toggle-play-pause',
  'skip-backward',
  'skip-forward',
  'toggle-mute',
  'set-volume',
  'set-playback-rate',
  'audio-loaded',
  'audio-error',
  'update-progress',
  'update-duration',
  'update-volume',
  'update-playback-rate',
  'seek',
])

const internalAudioElement = ref(null)
const isDragging = ref(false)
const draggingPercent = ref(0)
const svgElement = ref(null)
const arcReference = ref(null)
let rafId = null

const displayProgress = computed(() => {
  return isDragging.value ? draggingPercent.value : (props.progressPercent || 0)
})

// --- Arc geometry (internal to this component) ---

const arcReferencePath = computed(() => {
  const radius = 106
  const centerX = 130
  const centerY = 115
  const startAngle = 178
  const endAngle = 274

  const startRad = (startAngle * Math.PI) / 180
  const endRad = (endAngle * Math.PI) / 180

  const startX = centerX + radius * Math.cos(startRad)
  const startY = centerY + radius * Math.sin(startRad)
  const endX = centerX + radius * Math.cos(endRad)
  const endY = centerY + radius * Math.sin(endRad)

  const largeArcFlag = endAngle - startAngle > 180 ? 1 : 0
  return `M ${startX} ${startY} A ${radius} ${radius} 0 ${largeArcFlag} 1 ${endX} ${endY}`
})

const tickMarks = computed(() => {
  const ticks = []
  const numTicks = 90
  const radius = 106
  const centerX = 130
  const centerY = 115
  const startAngle = 178
  const endAngle = 274
  const tickLength = 5

  for (let i = 0; i <= numTicks; i++) {
    const progress = i / numTicks
    const angle = startAngle + (endAngle - startAngle) * progress
    const radian = (angle * Math.PI) / 180

    const x1 = centerX + radius * Math.cos(radian)
    const y1 = centerY + radius * Math.sin(radian)
    const x2 = centerX + (radius + tickLength) * Math.cos(radian)
    const y2 = centerY + (radius + tickLength) * Math.sin(radian)

    ticks.push({
      index: i,
      progress: (i / numTicks) * 100,
      x1, y1, x2, y2
    })
  }
  return ticks
})

// --- Arc drag handling (internal) ---

function startDragArc(event) {
  if (!props.duration || props.duration === 0) return
  isDragging.value = true
  handleDrag(event)
}

function dragArc(event) {
  if (!isDragging.value) return
  if (rafId !== null) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(() => handleDrag(event))
}

function stopDragArc() {
  if (!isDragging.value) return
  isDragging.value = false
  if (rafId !== null) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
  if (props.duration > 0) {
    const newTime = (draggingPercent.value / 100) * props.duration
    emit('seek', newTime)
  }
}

function handleDrag(event) {
  if (!props.duration || !arcReference.value) return
  const svg = svgElement.value
  if (!svg) return

  const pt = svg.createSVGPoint()
  pt.x = event.clientX
  pt.y = event.clientY
  const svgP = pt.matrixTransform(svg.getScreenCTM().inverse())

  const path = arcReference.value
  const pathLength = path.getTotalLength()

  let minDistance = Infinity
  let closestPoint = 0
  const sampleCount = 100

  for (let i = 0; i <= sampleCount; i++) {
    const length = (i / sampleCount) * pathLength
    const point = path.getPointAtLength(length)
    const distance = Math.sqrt(
      Math.pow(point.x - svgP.x, 2) + Math.pow(point.y - svgP.y, 2)
    )
    if (distance < minDistance) {
      minDistance = distance
      closestPoint = length
    }
  }

  draggingPercent.value = (closestPoint / pathLength) * 100
}

defineExpose({
  audioElement: internalAudioElement
})
</script>

<style scoped>
/* Audio player styles */
.audio-player-container {
  margin-bottom: 24px;
  overflow: visible;
}

.audio-error {
  padding: 16px;
  background: rgba(255, 235, 238, 0.9);
  border-left: 4px solid var(--color-danger-dark);
  border-radius: 8px;
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: 0 2px 8px rgba(var(--color-danger-rgb), 0.1);
}

.error-message {
  color: var(--color-danger-dark);
  font-size: 0.9rem;
  line-height: 1.5;
}

.btn-retry {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  background: var(--main-bg);
  color: var(--color-danger-dark);
  border: 1px solid var(--color-danger-dark);
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  transition: all 0.2s ease;
  align-self: flex-start;
}

.btn-retry:hover {
  background: var(--color-danger-dark);
  color: var(--color-white);
  box-shadow: 0 2px 8px rgba(var(--color-danger-rgb), 0.2);
  transform: translateY(-1px);
}

.btn-retry:active {
  transform: translateY(0);
}

.btn-retry svg {
  stroke: currentColor;
  flex-shrink: 0;
}

/* Circular player */
.custom-audio-player.circular-player {
  background: var(--main-bg);
  padding: 10px 5px 0px;
  border-radius: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0px;
  max-width: 280px;
  margin: 0 auto;
  position: relative;
}

/* Circular progress container */
.circular-progress-container {
  width: 100%;
  max-width: 280px;
  margin: 0px auto 0 -5px;
}

.progress-arc {
  width: 100%;
  height: auto;
  cursor: pointer;
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.1));
  user-select: none;
  -webkit-user-select: none;
  -moz-user-select: none;
  -ms-user-select: none;
}

/* Tick marks styles */
.tick-mark {
  stroke: var(--nav-active-bg);
  stroke-opacity: 0.5;
  transition: stroke 0.2s ease;
}

.tick-mark.tick-active {
  stroke: var(--nav-recent-bg);
  stroke-opacity: 1;
}

/* Time display */
.time-display-center {
  font-size: 0.8rem;
  color: var(--main-text);
  font-weight: 500;
  text-align: center;
  margin-top: -90px;
  margin-bottom: 0px;
}

/* Central control area - Play, fast forward, rewind */
.circular-controls-center {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 0px;
}

/* Volume and controls (includes info, volume, speed) */
.volume-and-controls {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1px;
  margin-top: 0px;
  padding: 0 15px;
}

/* Volume control area */
.volume-control-center {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 10px;
  flex: 1;
}

/* Mute button (at start of volume bar) */
.mute-btn-volume {
  width: 20px !important;
  height: 20px !important;
  min-width: 10px !important;
  min-height: 10px !important;
  padding: 0px !important;
  margin: 0;
  flex-shrink: 0;
  background: transparent !important;
  box-shadow: none !important;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: visible;
  border-radius: 4px !important;
}

.mute-btn-volume svg {
  display: block;
}

.mute-btn-volume:hover {
  background: var(--main-bg);
  transform: translateY(-1px);
}

.mute-btn-volume:active {
  transform: translateY(0);
}

.volume-slider-horizontal {
  width: 120px;
  height: 2.5px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--main-bg);
  border: var(--nav-bg) 0.5px solid;
  border-radius: 2px;
  outline: none;
  cursor: pointer;
  position: relative;
  z-index: 10;
}

.volume-slider-horizontal::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 6px;
  height: 14px;
  background: var(--nav-bg);
  border-left: 1px solid var(--nav-active-bg);
  border-right: 1px solid var(--nav-active-bg);
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

.volume-slider-horizontal::-moz-range-thumb {
  width: 10px;
  height: 10px;
  background: var(--main-primary);
  border-radius: 50%;
  cursor: pointer;
  border: none;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

/* Decorative element (top-left) */
.decorative-element {
  position: absolute;
  top: 5px;
  left: 15px;
  z-index: 5;
  color: var(--main-text);
  opacity: 0.6;
}

/* Keyboard shortcuts info wrapper */
.info-btn-wrapper {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 100;
}

.info-btn-wrapper :deep(.shortcuts-trigger-btn) {
  width: 40px;
  height: 20px;
}

/* Control buttons */
.audio-control-btn {
  background: #ffffff00;
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--main-text);
  transition: all 0.2s ease;
  position: relative;
  flex-shrink: 0;
  font-family: inherit;
}

.audio-control-btn:hover {
  transform: translateY(-2px);
  color: var(--main-primary);
}

.audio-control-btn:active {
  transform: translateY(0);
}

.audio-play-btn {
  width: 60px;
  height: 60px;
}

.audio-skip-btn {
  width: 46px;
  height: 46px;
}

.audio-control-label {
  position: absolute;
  font-size: 9px;
  font-weight: 700;
  bottom: 7px;
  color: var(--main-primary);
  font-family: inherit;
}

/* Rewind button number at bottom left */
.skip-backward .audio-control-label {
  left: 9px;
}

/* Fast forward button number at bottom right */
.skip-forward .audio-control-label {
  right: 9px;
}

/* Playback speed wrapper */
.speed-btn-wrapper :deep(.speed-trigger-btn) {
  width: 54px;
  height: 25px;
}

/* === Mobile: simplified horizontal player === */
@media (max-width: 768px) {
  .audio-player-container {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    margin: 0;
    z-index: 150;
    background: rgba(255, 255, 255, 0.95);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.1);
    padding: 12px calc(16px + env(safe-area-inset-right, 0px)) 12px calc(16px + env(safe-area-inset-left, 0px));
    padding-bottom: calc(12px + env(safe-area-inset-bottom, 0px));
  }

  :root[data-theme="dark"] .audio-player-container {
    background: rgba(40, 40, 40, 0.95);
  }

  .audio-error {
    padding: 8px 12px;
    margin-bottom: 0;
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }

  .error-message {
    font-size: 0.8rem;
    flex: 1;
  }

  .btn-retry {
    padding: 6px 12px;
    font-size: 0.75rem;
  }

  /* Hide circular elements */
  .custom-audio-player.circular-player {
    max-width: 100%;
    padding: 0;
    background: transparent;
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }

  .circular-progress-container,
  .decorative-element,
  .info-btn-wrapper {
    display: none !important;
  }

  /* Time display */
  .time-display-center {
    font-size: 0.7rem;
    margin: 0;
    min-width: 70px;
    text-align: center;
    order: 2;
  }

  /* Control buttons horizontal */
  .circular-controls-center {
    margin: 0;
    gap: 4px;
    order: 1;
  }

  .audio-play-btn {
    width: 40px;
    height: 40px;
  }

  .audio-play-btn svg {
    width: 22px;
    height: 22px;
  }

  .audio-skip-btn {
    width: 32px;
    height: 32px;
  }

  .audio-skip-btn svg {
    width: 14px;
    height: 14px;
  }

  .audio-control-label {
    display: none;
  }

  /* Volume and speed controls */
  .volume-and-controls {
    flex: 1;
    margin: 0;
    padding: 0;
    gap: 8px;
    order: 3;
  }

  .volume-control-center {
    gap: 4px;
  }

  .mute-btn-volume {
    width: 18px !important;
    height: 18px !important;
  }

  .mute-btn-volume svg {
    width: 16px;
    height: 16px;
  }

  .volume-slider-horizontal {
    width: 60px;
  }

  .speed-btn-wrapper {
    order: 4;
  }

  .speed-btn-wrapper :deep(.speed-trigger-btn) {
    width: 40px;
    height: 24px;
    border-radius: 8px;
  }

  .speed-btn-wrapper :deep(.speed-label) {
    font-size: 0.75rem;
  }

}

/* Small phone adjustments */
@media (max-width: 480px) {
  .audio-player-container {
    padding: 10px calc(12px + env(safe-area-inset-right, 0px)) 10px calc(12px + env(safe-area-inset-left, 0px));
    padding-bottom: calc(10px + env(safe-area-inset-bottom, 0px));
  }

  .time-display-center {
    font-size: 0.65rem;
    min-width: 60px;
  }

  .audio-play-btn {
    width: 36px;
    height: 36px;
  }

  .audio-play-btn svg {
    width: 20px;
    height: 20px;
  }

  .audio-skip-btn {
    width: 28px;
    height: 28px;
  }

  .volume-slider-horizontal {
    width: 50px;
  }

  .speed-btn {
    width: 36px;
  }

  .speed-label {
    font-size: 0.7rem;
  }
}
</style>
