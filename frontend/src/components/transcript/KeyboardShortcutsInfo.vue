<template>
  <div class="keyboard-shortcuts-info" :class="popDirection">
    <button class="shortcuts-trigger-btn" :title="$t('audioPlayer.keyboardShortcuts')">
      <svg width="32" height="24" viewBox="0 0 48 36" fill="currentColor">
        <circle cx="9" cy="8" r="2.5" fill="currentColor"/>
        <circle cx="19" cy="8" r="2.5" fill="currentColor"/>
        <circle cx="29" cy="8" r="2.5" fill="currentColor"/>
        <circle cx="39" cy="8" r="2" fill="none" stroke="currentColor" stroke-width="1"/>
        <circle cx="9" cy="18" r="2" fill="none" stroke="currentColor" stroke-width="1"/>
        <circle cx="19" cy="18" r="2" fill="none" stroke="currentColor" stroke-width="1"/>
        <circle cx="29" cy="18" r="2" fill="none" stroke="currentColor" stroke-width="1"/>
        <circle cx="39" cy="18" r="2.5" fill="currentColor"/>
        <circle cx="9" cy="28" r="2" fill="none" stroke="currentColor" stroke-width="1"/>
        <circle cx="19" cy="28" r="2" fill="none" stroke="currentColor" stroke-width="1"/>
        <circle cx="29" cy="28" r="2" fill="none" stroke="currentColor" stroke-width="1"/>
        <circle cx="39" cy="28" r="2.5" fill="currentColor"/>
      </svg>
    </button>
    <div class="shortcuts-tooltip">
      <div class="shortcuts-title">{{ $t('audioPlayer.audioControlShortcuts') }}</div>
      <div class="shortcuts-section">
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>Space</kbd>
          <span>{{ $t('audioPlayer.playPause') }}</span>
        </div>
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>←</kbd>
          <span>{{ $t('audioPlayer.rewind10sShortcut') }}</span>
        </div>
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>→</kbd>
          <span>{{ $t('audioPlayer.fastForward10sShortcut') }}</span>
        </div>
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>↑</kbd>
          <span>{{ $t('audioPlayer.speedUp') }}</span>
        </div>
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>↓</kbd>
          <span>{{ $t('audioPlayer.speedDown') }}</span>
        </div>
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>,</kbd>
          <span>{{ $t('audioPlayer.rewind5s') }}</span>
        </div>
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>.</kbd>
          <span>{{ $t('audioPlayer.fastForward5s') }}</span>
        </div>
        <div class="shortcut-item">
          <kbd>{{ modifierKeyLabel }}</kbd> + <kbd>M</kbd>
          <span>{{ $t('audioPlayer.toggleMute') }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { modifierKeyLabel } from '../../utils/platform'

const { t: $t } = useI18n()

defineProps({
  popDirection: {
    type: String,
    default: 'pop-up',
    validator: v => ['pop-up', 'pop-right'].includes(v)
  }
})
</script>

<style scoped>
.keyboard-shortcuts-info {
  position: relative;
}

.shortcuts-trigger-btn {
  background: transparent;
  border: none;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--main-text);
  transition: all 0.2s ease;
}

.shortcuts-trigger-btn:hover {
  background: var(--main-bg);
}

/* Tooltip 共用樣式 */
.shortcuts-tooltip {
  position: absolute;
  background: var(--main-bg);
  border-radius: 12px;
  padding: 12px;
  display: none;
  flex-direction: column;
  gap: 8px;
  z-index: 99999;
  min-width: 220px;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

/* 向上彈出（AudioPlayer 預設） */
.pop-up .shortcuts-tooltip {
  bottom: 100%;
  right: 0;
  margin-bottom: 8px;
}

.pop-up .shortcuts-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  right: 20px;
  border: 6px solid transparent;
  border-top-color: var(--main-bg);
}

/* 向右彈出（收合側邊欄） */
.pop-right .shortcuts-tooltip {
  left: 100%;
  top: 50%;
  transform: translateY(-50%);
  margin-left: 12px;
}

.pop-right .shortcuts-tooltip::after {
  content: '';
  position: absolute;
  top: 50%;
  right: 100%;
  transform: translateY(-50%);
  border: 6px solid transparent;
  border-right-color: var(--main-bg);
}

.keyboard-shortcuts-info:hover .shortcuts-tooltip,
.shortcuts-tooltip:hover {
  display: flex;
}

.shortcuts-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--main-text);
  margin-bottom: 4px;
}

.shortcuts-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.shortcut-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.75rem;
  color: var(--main-text);
}

.shortcut-item kbd {
  background: var(--main-bg);
  padding: 3px 6px;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 600;
  font-family: monospace;
  color: var(--main-primary);
  min-width: 28px;
  text-align: center;
}

.shortcut-item span {
  flex: 1;
  color: var(--main-text);
  font-size: 0.75rem;
}
</style>
