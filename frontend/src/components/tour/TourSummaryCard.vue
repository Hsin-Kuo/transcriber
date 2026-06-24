<template>
  <!-- 導覽專用的「假」AI 摘要卡（展開狀態，純展示）。
       不動真實 AISummary 的內部展開/載入邏輯，導覽時直接以此卡展示「AI 摘要長怎樣」。 -->
  <div class="tour-summary-card" data-tour="t-summary">
    <div class="ts-header">
      <div class="ts-left">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3c.132 0 .263 0 .393 0a7.5 7.5 0 0 0 7.92 12.446a9 9 0 1 1 -8.313 -12.454z" />
          <path d="M17 4a2 2 0 0 0 2 2a2 2 0 0 0 -2 2a2 2 0 0 0 -2 -2a2 2 0 0 0 2 -2" />
          <path d="M19 11h2m-1 -1v2" />
        </svg>
        <span class="ts-title">{{ t('aiSummary.title') }}</span>
      </div>
      <span class="ts-badge">{{ t('aiSummary.completed') }}</span>
    </div>

    <div class="ts-body">
      <div class="ts-section">
        <h4 class="ts-section-title">{{ t('aiSummary.executiveSummary') }}</h4>
        <p class="ts-summary-text">{{ demo.summary }}</p>
      </div>
      <div class="ts-section">
        <h4 class="ts-section-title">{{ t('aiSummary.keyPoints') }}</h4>
        <ul class="ts-points">
          <li v-for="(point, i) in demo.points" :key="i">{{ point }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { getDemoSummary } from '../../utils/tourFixtures'

const { t, locale } = useI18n()
const demo = computed(() => getDemoSummary(locale.value))
</script>

<style scoped>
.tour-summary-card {
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  margin-bottom: 8px;
  padding-bottom: 12px;
}

.ts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 4px;
}

.ts-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--main-primary, #dd8448);
}

.ts-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--main-text, #4a5568);
}

.ts-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-teal, #2c9c8f);
  background: rgba(44, 156, 143, 0.12);
  padding: 2px 10px;
  border-radius: 10px;
}

.ts-body {
  padding: 0 4px;
}

.ts-section + .ts-section {
  margin-top: 14px;
}

.ts-section-title {
  font-size: 13px;
  font-weight: 700;
  color: rgba(var(--color-text-dark-rgb, 74, 85, 104), 0.7);
  margin: 0 0 6px;
}

.ts-summary-text {
  font-size: 14px;
  line-height: 1.7;
  color: var(--main-text, #4a5568);
  margin: 0;
}

.ts-points {
  margin: 0;
  padding-left: 18px;
}

.ts-points li {
  font-size: 14px;
  line-height: 1.7;
  color: var(--main-text, #4a5568);
}
</style>
