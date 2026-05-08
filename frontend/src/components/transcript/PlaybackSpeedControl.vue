<template>
  <div class="speed-control" :class="[popDirection, { 'is-open': showDropdown }]" @click.stop>
    <button
      class="speed-trigger-btn"
      :title="$t('audioPlayer.playbackSpeed', { rate: playbackRate })"
      @click.stop="toggleDropdown"
    >
      <span class="speed-label">{{ playbackRate }}x</span>
    </button>
    <div class="speed-dropdown" @click.stop>
      <button
        v-for="rate in rates"
        :key="rate"
        class="speed-option"
        :class="{ active: playbackRate === rate }"
        @click.stop="selectRate(rate)"
      >
        {{ rate }}x
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

defineProps({
  playbackRate: {
    type: Number,
    default: 1
  },
  popDirection: {
    type: String,
    default: 'pop-up',
    validator: v => ['pop-up', 'pop-right'].includes(v)
  }
})

const emit = defineEmits(['set-playback-rate'])

const rates = [0.5, 0.75, 1, 1.25, 1.5, 2]
const showDropdown = ref(false)

function toggleDropdown() {
  showDropdown.value = !showDropdown.value
  if (showDropdown.value) {
    document.addEventListener('click', closeDropdown)
  } else {
    document.removeEventListener('click', closeDropdown)
  }
}

function closeDropdown() {
  showDropdown.value = false
  document.removeEventListener('click', closeDropdown)
}

function selectRate(rate) {
  emit('set-playback-rate', rate)
  closeDropdown()
}

onUnmounted(() => {
  document.removeEventListener('click', closeDropdown)
})
</script>

<style scoped>
.speed-control {
  position: relative;
}

.speed-trigger-btn {
  background: transparent;
  border: none;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--main-text);
  transition: all 0.2s ease;
}

.speed-trigger-btn:hover {
  background: var(--main-bg);
}

.speed-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--main-text);
}

/* Dropdown 共用樣式 */
.speed-dropdown {
  position: absolute;
  background: var(--main-bg);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  border-radius: 12px;
  padding: 4px;
  display: none;
  flex-direction: column;
  gap: 4px;
  z-index: 99999;
  min-width: 70px;
}

/* 向上彈出（AudioPlayer 預設） */
.pop-up .speed-dropdown {
  bottom: 100%;
  right: 0;
  margin-bottom: 8px;
}

.pop-up .speed-dropdown::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  height: 12px;
}

/* 向右彈出（收合側邊欄） */
.pop-right .speed-dropdown {
  left: 100%;
  top: 50%;
  transform: translateY(-50%);
  margin-left: 12px;
}

.pop-right .speed-dropdown::after {
  content: '';
  position: absolute;
  top: 50%;
  right: 100%;
  transform: translateY(-50%);
  border: 6px solid transparent;
  border-right-color: var(--main-bg);
}

.speed-control.is-open .speed-dropdown {
  display: flex;
}

.speed-option {
  background: transparent;
  box-shadow: none;
  border: none;
  padding: 6px 0px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--main-text);
  transition: all 0.2s ease;
  text-align: center;
}

.speed-option:hover {
  background: rgba(163, 177, 198, 0.15);
  color: var(--main-primary);
}

.speed-option.active {
  background: rgba(163, 177, 198, 0.2);
  color: var(--main-primary);
  font-weight: 700;
}

</style>
