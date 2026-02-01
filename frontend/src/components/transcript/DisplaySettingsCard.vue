<template>
  <div class="display-settings-card">
    <!-- 旋鈕列：字體選擇 & 時間標記 & 主題色 -->
    <div class="knob-row">
      <!-- 字體選擇 -->
      <div class="font-selector">
        <button
          class="font-option"
          :class="{ active: fontFamily === 'sans-serif' }"
          @click="$emit('update:fontFamily', 'sans-serif')"
          :title="$t('displaySettings.sansSerif')"
        >
          <span class="font-dot"></span>
          <span class="font-label">Aa123</span>
        </button>
        <button
          class="font-option serif"
          :class="{ active: fontFamily === 'serif' }"
          @click="$emit('update:fontFamily', 'serif')"
          :title="$t('displaySettings.serif')"
        >
          <span class="font-dot"></span>
          <span class="font-label">Aa123</span>
        </button>
      </div>
      <div class="knob-cell">
        <!-- 段落模式：時間標記切換 -->
        <div v-if="displayMode === 'paragraph'" class="knob-wrapper" :title="$t('displaySettings.timecodeMarkers')">
          <span class="knob-dot"></span>
          <label class="knob" :class="{ active: showTimecodeMarkers }">
            <input type="checkbox" :checked="showTimecodeMarkers" @change="$emit('update:showTimecodeMarkers', $event.target.checked)" />
            <span class="knob-indicator"></span>
          </label>
          <span class="knob-icon knob-icon-text">{{ $t('transcriptDetail.timecodeMarkers') }}</span>
        </div>
        <!-- 字幕模式：時間格式切換 -->
        <div v-else class="knob-wrapper" :title="$t('subtitleTable.timeFormat')">
          <span class="knob-icon knob-icon-left knob-icon-text">{{ $t('subtitleTable.startTime') }}</span>
          <label class="knob" :class="{ active: timeFormat === 'range' }">
            <input type="checkbox" :checked="timeFormat === 'range'" @change="$emit('update:timeFormat', $event.target.checked ? 'range' : 'start')" />
            <span class="knob-indicator"></span>
          </label>
          <span class="knob-icon knob-icon-text">{{ $t('subtitleTable.timeRange') }}</span>
        </div>
      </div>
      <div class="knob-cell">
        <div class="knob-wrapper" :title="$t('displaySettings.darkMode')">
          <!-- 左下角：太陽 icon -->
          <svg class="knob-icon knob-icon-left" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5"></circle>
            <line x1="12" y1="1" x2="12" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="23"></line>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
            <line x1="1" y1="12" x2="3" y2="12"></line>
            <line x1="21" y1="12" x2="23" y2="12"></line>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
          </svg>
          <label class="knob" :class="{ active: isDarkMode }">
            <input type="checkbox" :checked="isDarkMode" @change="$emit('update:isDarkMode', $event.target.checked)" />
            <span class="knob-indicator"></span>
          </label>
          <!-- 右下角：月亮 icon -->
          <svg class="knob-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
          </svg>
        </div>
      </div>
    </div>

    <!-- 字體大小 & 粗細 Sliders -->
    <div class="sliders-group">
      <div class="sliders-column">
        <div class="slider-row">
          <svg class="slider-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :title="$t('displaySettings.fontSize')">
            <polyline points="4 7 4 4 20 4 20 7"></polyline>
            <line x1="9" y1="20" x2="15" y2="20"></line>
            <line x1="12" y1="4" x2="12" y2="20"></line>
          </svg>
          <input
            type="range"
            min="12"
            max="24"
            step="1"
            :value="fontSize"
            @input="$emit('update:fontSize', Number($event.target.value))"
            class="slider"
            :title="$t('displaySettings.fontSize')"
          />
        </div>
        <div class="slider-row">
          <svg class="slider-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" :title="$t('displaySettings.fontWeight')">
            <path d="M6 4h8a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path>
            <path d="M6 12h9a4 4 0 0 1 4 4 4 4 0 0 1-4 4H6z"></path>
          </svg>
          <input
            type="range"
            min="300"
            max="700"
            step="100"
            :value="fontWeight"
            @input="$emit('update:fontWeight', Number($event.target.value))"
            class="slider"
            :title="$t('displaySettings.fontWeight')"
          />
        </div>
      </div>
      <div class="display-panel">
        <span class="display-row">{{ fontSize }}px</span>
        <span class="display-row">{{ fontWeight }}</span>
      </div>
    </div>

    <!-- 字幕模式：疏密度調整 -->
    <div v-if="displayMode === 'subtitle'" class="density-group">
      <div class="density-slider-row">
        <!-- 疏 icon: 間距較大的橫線 -->
        <svg class="density-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" :title="$t('subtitleTable.sparse')">
          <line x1="4" y1="6" x2="20" y2="6"></line>
          <line x1="4" y1="13" x2="12" y2="13"></line>
          <line x1="4" y1="20" x2="17" y2="20"></line>
        </svg>
        <input
          type="range"
          :value="densityThreshold"
          @input="$emit('update:densityThreshold', Number($event.target.value))"
          min="0"
          max="120"
          step="1"
          class="slider density-slider"
        />
        <!-- 密 icon: 間距較小的橫線 -->
        <svg class="density-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" :title="$t('subtitleTable.dense')">
          <line x1="4" y1="5" x2="20" y2="5"></line>
          <line x1="4" y1="10" x2="20" y2="10"></line>
          <line x1="4" y1="15" x2="15" y2="15"></line>
          <line x1="4" y1="20" x2="20" y2="20"></line>
        </svg>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

const { t: $t } = useI18n()

// Props
defineProps({
  displayMode: {
    type: String,
    default: 'paragraph'
  },
  showTimecodeMarkers: {
    type: Boolean,
    default: false
  },
  timeFormat: {
    type: String,
    default: 'start'
  },
  isDarkMode: {
    type: Boolean,
    default: false
  },
  fontSize: {
    type: Number,
    default: 16
  },
  fontWeight: {
    type: Number,
    default: 400
  },
  fontFamily: {
    type: String,
    default: 'sans-serif'
  },
  densityThreshold: {
    type: Number,
    default: 30
  }
})

// Emits
defineEmits([
  'update:showTimecodeMarkers',
  'update:timeFormat',
  'update:isDarkMode',
  'update:fontSize',
  'update:fontWeight',
  'update:fontFamily',
  'update:densityThreshold'
])
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');
.display-settings-card {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 16px;
  border-radius: 12px;
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.setting-label {
  display: flex;
  align-items: center;
  color: var(--main-text-light);
  cursor: default;
}

.setting-label svg {
  opacity: 0.7;
}

/* Knob Row */
.knob-row {
  display: flex;
  align-items: center;
}

.knob-cell {
  flex: 1;
  display: flex;
  justify-content: center;
}

/* Knob Wrapper */
.knob-wrapper {
  position: relative;
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 左下角的灰點 */
.knob-dot {
  position: absolute;
  width: 5px;
  height: 5px;
  background: rgba(var(--color-text-dark-rgb), 0.6);
  border-radius: 50%;
  bottom: 12px;
  left: 8px;
}

/* 右下角的 icon */
.knob-icon {
  position: absolute;
  bottom: 7px;
  right: 4px;
  color: var(--nav-text);
  /* opacity: 0.5; */
}

.knob-icon-text {
  font-size: 9px;
  font-weight: 500;
  top: auto;
  bottom: 1px;
  right: -7px;
  left: auto;
  transform: none;
  width: 24px;
  text-align: right;
  line-height: 1.2;
}

.knob-icon-left {
  left: 4px;
  right: auto;
}

.knob-icon-left.knob-icon-text {
  left: -7px;
  right: auto;
  text-align: left;
}

/* Knob Switch */
.knob {
  position: relative;
  display: inline-block;
  width: 32px;
  height: 32px;
  top: -5px;
  background: #dedede;
  border: 0.5px solidf;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.3s ease;
}

.knob input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

.knob-indicator {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 2px;
  height: 14px;
  background-color: var(--nav-active-bg);
  border-radius: 1px;
  transform-origin: center bottom;
  transform: translate(-50%, -100%) rotate(230deg);
  transition: transform 0.3s ease, background-color 0.3s ease;
}

.knob.active {
  background: var(--nav-active-bg);
}

.knob.active .knob-indicator {
  background-color: white;
  transform: translate(-50%, -100%) rotate(130deg);
}

.knob:hover {
  box-shadow: 0 0 0 3px rgba(var(--main-primary-rgb, 59, 130, 246), 0.2);
}

/* Slider */
.slider-container {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  max-width: 100%;
}

.slider {
  flex: 1;
  height: 14px;
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  outline: none;
}

.slider::-webkit-slider-runnable-track {
  width: 100%;
  height: 3px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 2px;
  border: 0.5px solid #999;
}

.slider::-moz-range-track {
  width: 100%;
  height: 4px;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 2px;
}

.slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 7px;
  height: 14px;
  margin-top: -5px;
  background: var(--nav-bg);
  border-right: 1.5px solid var(--nav-active-bg);
  border-left: 1.5px solid var(--nav-active-bg);
  border-radius: 10%;
  cursor: pointer;
  transition: transform 0.2s;
}

.slider::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.slider::-moz-range-thumb {
  width: 14px;
  height: 14px;
  background: var(--main-primary);
  border-radius: 50%;
  cursor: pointer;
  border: none;
}

.slider-value {
  font-size: 12px;
  color: var(--main-text-light);
  min-width: 36px;
  text-align: right;
}

/* Sliders Group */
.sliders-group {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.sliders-column {
  display: flex;
  flex-direction: column;
  gap: 18px;
  flex: 1;
  max-width: 180px;
}

.slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.slider-icon {
  flex-shrink: 0;
  color: var(--nav-text);
  opacity: 0.6;
}

.display-panel {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-family: 'VT323', monospace;
  font-size: 14px;
  color: #ffffff;
  background: #101010;
  padding: 2px 10px;
  border-radius: 3px;
  min-width: 52px;
  text-align: right;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.6);
  border: 1px solid #222;
  letter-spacing: 1px;
}

.display-row {
  line-height: 1.3;
}

/* Font Selector */
.font-selector {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
}

.font-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border: none;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.font-option.serif {
  font-family: Georgia, 'Times New Roman', serif;
}

.font-option .font-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(var(--color-text-dark-rgb), 0.4);
  transition: background 0.2s;
}

.font-option .font-label {
  font-size: 12px;
  font-weight: 400;
  color: rgba(var(--color-text-dark-rgb), 0.5);
  transition: color 0.2s;
}

.font-option:hover .font-label {
  color: rgba(var(--color-text-dark-rgb), 0.7);
}

.font-option.active .font-dot {
  background: var(--nav-active-bg);
}

.font-option.active .font-label {
  color: var(--color-text-dark);
}

/* Density Group */
.density-group {
  padding-top: 12px;
  border-top: 1px solid rgba(163, 177, 198, 0.15);
}

.density-slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.density-icon {
  flex-shrink: 0;
  color: var(--nav-text);
  opacity: 0.6;
}

.density-slider {
  flex: 1;
}
</style>
