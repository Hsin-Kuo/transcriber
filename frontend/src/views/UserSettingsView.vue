<template>
  <div class="settings-container">
    <div class="settings-header">
      <h1>使用者設定</h1>
      <p>管理您的帳戶資訊和配額使用情況</p>
    </div>

    <!-- 使用者資訊 -->
    <div class="card user-info-card">
      <h2>帳戶資訊</h2>
      <div class="info-item">
        <span class="info-label">電子郵件</span>
        <span class="info-value">{{ authStore.user?.email }}</span>
      </div>
      <div class="info-item">
        <span class="info-label">帳戶類型</span>
        <span class="info-value">{{ quotaTierName }}</span>
      </div>
    </div>

    <!-- 配額顯示 -->
    <div class="quota-card electric-card">
      <div class="electric-inner">
        <div class="electric-border-outer">
          <div class="electric-main quota-content">
            <div class="quota-header">
              <h3>配額使用情況</h3>
              <span class="quota-tier">{{ quotaTierName }}</span>
            </div>

            <div class="quota-items">
              <div class="quota-item">
                <div class="quota-label">
                  <span>轉錄次數</span>
                  <span class="quota-value">{{ authStore.usage?.transcriptions || 0 }} / {{ authStore.quota?.max_transcriptions || 0 }}</span>
                </div>
                <div class="quota-bar">
                  <div
                    class="quota-progress"
                    :class="{ 'quota-warning': authStore.quotaPercentage?.transcriptions > 80 }"
                    :style="{ width: `${authStore.quotaPercentage?.transcriptions || 0}%` }"
                  ></div>
                </div>
                <div class="quota-remaining">
                  剩餘 {{ authStore.remainingQuota?.transcriptions || 0 }} 次
                </div>
              </div>

              <div class="quota-item">
                <div class="quota-label">
                  <span>轉錄時長</span>
                  <span class="quota-value">{{ Math.round(authStore.usage?.duration_minutes || 0) }} / {{ authStore.quota?.max_duration_minutes || 0 }} 分鐘</span>
                </div>
                <div class="quota-bar">
                  <div
                    class="quota-progress"
                    :class="{ 'quota-warning': authStore.quotaPercentage?.duration > 80 }"
                    :style="{ width: `${authStore.quotaPercentage?.duration || 0}%` }"
                  ></div>
                </div>
                <div class="quota-remaining">
                  剩餘 {{ Math.round(authStore.remainingQuota?.duration || 0) }} 分鐘
                </div>
              </div>

              <div class="quota-item">
                <div class="quota-label">
                  <span>儲存空間</span>
                  <span class="quota-value">{{ formatBytes(authStore.usage?.storage_bytes || 0) }} / {{ formatBytes(authStore.quota?.max_storage_bytes || 0) }}</span>
                </div>
                <div class="quota-bar">
                  <div
                    class="quota-progress"
                    :class="{ 'quota-warning': authStore.quotaPercentage?.storage > 80 }"
                    :style="{ width: `${authStore.quotaPercentage?.storage || 0}%` }"
                  ></div>
                </div>
                <div class="quota-remaining">
                  剩餘 {{ formatBytes(authStore.remainingQuota?.storage || 0) }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()

// 配額層級名稱
const quotaTierName = computed(() => {
  const tier = authStore.quota?.tier || 'free'
  const tierNames = {
    free: '免費版',
    basic: '基礎版',
    pro: '專業版',
    enterprise: '企業版'
  }
  return tierNames[tier] || '未知'
})

// 格式化位元組大小
function formatBytes(bytes) {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
}
</script>

<style scoped>
.settings-container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 0 20px;
}

.settings-header {
  margin-bottom: 32px;
  text-align: center;
}

.settings-header h1 {
  font-size: 2rem;
  color: var(--neu-primary);
  margin: 0 0 8px 0;
  font-weight: 700;
}

.settings-header p {
  color: var(--neu-text-light);
  margin: 0;
  font-size: 1rem;
}

.user-info-card {
  margin-bottom: 24px;
}

.user-info-card h2 {
  font-size: 1.25rem;
  color: var(--neu-primary);
  margin: 0 0 20px 0;
  font-weight: 600;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid rgba(163, 177, 198, 0.2);
}

.info-item:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 0.95rem;
  color: var(--neu-text-light);
  font-weight: 500;
}

.info-value {
  font-size: 0.95rem;
  color: var(--neu-text);
  font-weight: 600;
}

/* 配額卡片樣式 */
.quota-card {
  margin: 24px 0;
}

.quota-content {
  padding: 24px;
  background: var(--neu-bg);
}

.quota-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid rgba(163, 177, 198, 0.2);
}

.quota-header h3 {
  margin: 0;
  font-size: 1.25rem;
  color: var(--neu-primary);
  font-weight: 600;
}

.quota-tier {
  padding: 6px 16px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
  border-radius: 12px;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--neu-primary);
}

.quota-items {
  display: grid;
  gap: 24px;
}

.quota-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.quota-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.95rem;
  color: var(--neu-text);
  font-weight: 500;
}

.quota-value {
  font-weight: 600;
  color: var(--neu-primary);
}

.quota-bar {
  height: 10px;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-inset);
  border-radius: 8px;
  overflow: hidden;
}

.quota-progress {
  height: 100%;
  background: linear-gradient(90deg, var(--neu-primary), var(--neu-primary-light));
  border-radius: 8px;
  transition: width 0.3s ease, background 0.3s ease;
  box-shadow: 0 0 8px rgba(108, 139, 163, 0.3);
}

.quota-progress.quota-warning {
  background: linear-gradient(90deg, #ff6b35, #ff8c42);
  box-shadow: 0 0 8px rgba(255, 107, 53, 0.4);
}

.quota-remaining {
  font-size: 0.85rem;
  color: var(--neu-text-light);
  text-align: right;
}

@media (max-width: 768px) {
  .settings-container {
    padding: 0 16px;
  }

  .settings-header h1 {
    font-size: 1.75rem;
  }

  .quota-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .quota-tier {
    align-self: flex-end;
  }
}
</style>
