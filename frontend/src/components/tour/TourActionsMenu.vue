<template>
  <!-- 導覽專用的「假」下拉選單（純展示）。
       為何不用真實 dropdown：真實面板是 absolute、且 driver 會對 active 元素的父層
       強制 overflow:hidden，導致溢出的面板內容被裁掉看不到。此元件 teleport 到 body、
       內容都在自身範圍內、z-index 壓在 overlay 之上 popover 之下，渲染穩定可控。 -->
  <Teleport to="body">
    <div v-if="visible" class="tour-actions-menu" data-tour="t-actions">
      <div class="tour-menu-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        <span>{{ t('transcriptDetail.download') }}</span>
      </div>
      <div class="tour-menu-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
        <span>{{ t('transcriptDetail.copyText') }}</span>
      </div>
      <div class="tour-menu-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="18" cy="5" r="3" />
          <circle cx="6" cy="12" r="3" />
          <circle cx="18" cy="19" r="3" />
          <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
          <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
        </svg>
        <span>{{ t('shared.shareButton') }}</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  visible: { type: Boolean, default: false },
})

const { t } = useI18n()
</script>

<style scoped>
.tour-actions-menu {
  position: fixed;
  top: 60px;
  right: 24px;
  z-index: 10001; /* 高於 driver overlay(10000)、低於 popover(1e9) */
  min-width: 160px;
  padding: 8px;
  background: var(--color-white, #ffffff);
  border: 1px solid rgba(163, 177, 198, 0.2);
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  gap: 4px;
  pointer-events: none; /* 純展示，不可互動 */
}

.tour-menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  color: var(--main-text, #4a5568);
  white-space: nowrap;
}

.tour-menu-item svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--main-primary, #dd8448);
}
</style>
