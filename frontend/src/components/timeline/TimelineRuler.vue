<template>
  <div class="timeline-ruler" :style="rulerStyle">
    <div
      v-for="mark in timeMarks"
      :key="mark.time"
      class="time-mark"
      :style="{ left: mark.position + 'px' }"
    >
      <div class="mark-line" :class="{ major: mark.major }"></div>
      <span v-if="mark.major" class="mark-label">{{ mark.label }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  zoom: {
    type: Number,
    required: true
  },
  duration: {
    type: Number,
    required: true
  }
})

const rulerStyle = computed(() => ({
  width: Math.max(props.duration * props.zoom, 100) + 'px'
}))

const timeMarks = computed(() => {
  const marks = []
  const totalWidth = props.duration * props.zoom

  // Determine mark interval based on zoom level
  let majorInterval = 10 // seconds
  let minorInterval = 1 // seconds

  if (props.zoom < 30) {
    majorInterval = 30
    minorInterval = 10
  } else if (props.zoom < 50) {
    majorInterval = 20
    minorInterval = 5
  } else if (props.zoom > 100) {
    majorInterval = 5
    minorInterval = 1
  }

  // Generate marks
  const maxTime = Math.ceil(props.duration)
  for (let time = 0; time <= maxTime; time += minorInterval) {
    const position = time * props.zoom
    const isMajor = time % majorInterval === 0

    marks.push({
      time,
      position,
      major: isMajor,
      label: formatTime(time)
    })
  }

  return marks
})

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)

  if (mins === 0) {
    return `${secs}s`
  }

  return `${mins}:${secs.toString().padStart(2, '0')}`
}
</script>

<style scoped>
.timeline-ruler {
  position: relative;
  height: 30px;
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  min-width: 100%;
}

.time-mark {
  position: absolute;
  top: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.mark-line {
  width: 1px;
  background: rgba(255, 255, 255, 0.2);
  height: 8px;
  margin-top: auto;
}

.mark-line.major {
  background: rgba(255, 255, 255, 0.4);
  height: 12px;
}

.mark-label {
  position: absolute;
  top: 4px;
  font-size: 11px;
  color: #aaa;
  font-family: monospace;
  user-select: none;
  white-space: nowrap;
  transform: translateX(-50%);
}
</style>
