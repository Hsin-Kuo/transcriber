<template>
  <div class="pagination">
    <!-- 第一頁 -->
    <button
      class="page-button first-page"
      :class="{ disabled: currentPage === 1 }"
      :disabled="currentPage === 1"
      @click="goToPage(1)"
    >
      &lt;&lt;
    </button>

    <!-- 前一頁 -->
    <button
      class="page-button nav-button prev"
      :class="{ disabled: currentPage === 1 }"
      :disabled="currentPage === 1"
      @click="prevPage"
    >
      &lt;
    </button>

    <!-- 當前頁數 -->
    <span class="current-page">
      {{ currentPage }} / {{ totalPages || '-' }}
    </span>

    <!-- 下一頁 -->
    <button
      class="page-button nav-button next"
      :class="{ disabled: currentPage === totalPages }"
      :disabled="currentPage === totalPages"
      @click="nextPage"
    >
      &gt;
    </button>

    <!-- 最末頁 -->
    <button
      class="page-button last-page"
      :class="{ disabled: currentPage === totalPages }"
      :disabled="currentPage === totalPages || totalPages === 0"
      @click="goToPage(totalPages)"
    >
      &gt;&gt;
    </button>
  </div>
</template>

<script setup>
const props = defineProps({
  currentPage: {
    type: Number,
    required: true
  },
  totalPages: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['update:currentPage'])

function goToPage(page) {
  if (page >= 1 && page <= props.totalPages && page !== props.currentPage) {
    emit('update:currentPage', page)
  }
}

function prevPage() {
  if (props.currentPage > 1) {
    emit('update:currentPage', props.currentPage - 1)
  }
}

function nextPage() {
  if (props.currentPage < props.totalPages) {
    emit('update:currentPage', props.currentPage + 1)
  }
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Doto:wght@100..900&display=swap');

.pagination {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  user-select: none;
}

/* 分頁按鈕 */
.page-button {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  font-family: 'Doto', sans-serif;
  font-size: 18px;
  font-weight: 700;
  color: var(--main-text);
  background: transparent;
  border: 1px solid rgba(var(--main-text-rgb, 0, 0, 0), 0);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

/* 導航按鈕 */
.nav-button {
  font-size: 18px;
  font-weight: 700;
}

/* 當前頁數 */
.current-page {
  font-size: 13px;
  font-weight: 400;
  color: var(--main-text);
  padding: 0 8px;
  min-width: 50px;
  text-align: center;
}

/* Hover 效果 */
.page-button:hover:not(.disabled) {
  color: var(--main-primary);
  /* border-color: var(--main-primary); */
  background: rgba(var(--main-primary-rgb, 59, 130, 246), 0.08);
}

/* 禁用狀態 */
.page-button.disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* === 響應式設計 === */

/* 平板以下 - 浮動固定在底部 */
@media (max-width: 768px) {
  .pagination {
    position: fixed;
    bottom: calc(70px + env(safe-area-inset-bottom, 0px));
    left: 50%;
    transform: translateX(-50%);
    gap: 6px;
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    padding: 8px 16px;
    border-radius: 20px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
    z-index: 99;
  }

  /* 深色模式 */
  :root[data-theme="dark"] .pagination {
    background: rgba(50, 50, 50, 0.85);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
  }

  .page-button {
    width: 28px;
    height: 28px;
    font-size: 14px;
  }

  .nav-button {
    font-size: 14px;
  }

  .current-page {
    font-size: 12px;
    padding: 0 6px;
    min-width: 44px;
  }
}

/* 小手機 */
@media (max-width: 480px) {
  .pagination {
    bottom: calc(62px + env(safe-area-inset-bottom, 0px));
    gap: 4px;
    padding: 6px 12px;
    border-radius: 16px;
  }

  .page-button {
    width: 26px;
    height: 26px;
    font-size: 13px;
  }

  .nav-button {
    font-size: 13px;
  }

  .current-page {
    font-size: 11px;
    padding: 0 4px;
    min-width: 40px;
  }
}
</style>
