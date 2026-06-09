<template>
  <Teleport to="body">
    <div v-if="quota" class="quota-overlay" @click.self="close">
      <div class="quota-modal" role="dialog" aria-modal="true" :aria-label="$t('quotaModal.title')">
        <div class="quota-icon" aria-hidden="true">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>

        <h2 class="quota-title">{{ $t('quotaModal.title') }}</h2>
        <p class="quota-message">{{ message }}</p>
        <p class="quota-hint">{{ ctaHint }}</p>

        <div class="quota-actions">
          <button class="quota-cta" @click="goPurchase">{{ ctaLabel }}</button>
          <button class="quota-later" @click="close">{{ $t('quotaModal.later') }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore } from '../stores/ui'
import { useAuthStore } from '../stores/auth'

const { t: $t } = useI18n()
const uiStore = useUiStore()
const authStore = useAuthStore()

const quota = computed(() => uiStore.quotaModal)
const isFree = computed(() => (authStore.quota?.tier || 'free') === 'free')

const message = computed(() =>
  quota.value?.type === 'ai_summaries'
    ? $t('quotaModal.aiMessage')
    : $t('quotaModal.durationMessage')
)

// 免費用戶引導升級；付費用戶引導加購（後端僅付費訂閱可加購）
const ctaLabel = computed(() => isFree.value ? $t('quotaModal.upgradeCta') : $t('quotaModal.addonCta'))
const ctaHint = computed(() => isFree.value ? $t('quotaModal.upgradeHint') : $t('quotaModal.addonHint'))

function close() {
  uiStore.closeQuotaModal()
}

function goPurchase() {
  uiStore.closeQuotaModal()
  uiStore.openPlanPanel()
}
</script>

<style scoped>
.quota-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.quota-modal {
  background: var(--upload-bg, #fff);
  border-radius: 16px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
  width: 100%;
  max-width: 380px;
  padding: 28px 24px 24px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.quota-icon {
  color: var(--main-primary);
  margin-bottom: 12px;
}

.quota-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--main-text);
  margin: 0 0 8px;
}

.quota-message {
  font-size: 0.92rem;
  color: var(--main-text);
  margin: 0 0 4px;
  line-height: 1.5;
}

.quota-hint {
  font-size: 0.82rem;
  color: var(--main-text-light);
  margin: 0 0 20px;
  line-height: 1.5;
}

.quota-actions {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quota-cta {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: 10px;
  background: var(--main-primary);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.quota-cta:hover { opacity: 0.9; transform: translateY(-1px); }

.quota-later {
  width: 100%;
  padding: 10px;
  border: none;
  background: transparent;
  color: var(--main-text-light);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.quota-later:hover { background: rgba(163, 177, 198, 0.12); color: var(--main-text); }
</style>
