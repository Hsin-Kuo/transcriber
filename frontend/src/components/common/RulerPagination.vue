<template>
  <div class="ruler-pagination">
    <!-- 1. 起點標記「0」 -->
    <div class="ruler-item empty">
      <div class="control-button start-label">
        0
      </div>
      <div class="ticks">
        <div class="tick tick-long"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-medium"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
      </div>
    </div>

    <!-- 2. 第一頁 -->
    <div class="ruler-item">
      <button
        class="control-button page-button first-page"
        :class="{ active: currentPage === 1, disabled: currentPage === 1 }"
        :disabled="currentPage === 1"
        @click="goToPage(1)"
      >
        &lt;&lt;
      </button>
      <div class="ticks">
        <div class="tick tick-long"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-medium"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
      </div>
    </div>

    <!-- 3. 前一頁 -->
    <div class="ruler-item">
      <button
        class="control-button nav-button prev"
        :class="{ disabled: currentPage === 1 }"
        :disabled="currentPage === 1"
        @click="prevPage"
      >
        &lt;
      </button>
      <div class="ticks">
        <div class="tick tick-long"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-medium"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
      </div>
    </div>

    <!-- 4. 當前頁數 -->
    <div class="ruler-item">
      <div class="control-button current-page">
        {{ currentPage }}
      </div>
      <div class="ticks">
        <div class="tick tick-long"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-medium"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
      </div>
    </div>

    <!-- 5. 下一頁 -->
    <div class="ruler-item">
      <button
        class="control-button nav-button next"
        :class="{ disabled: currentPage === totalPages }"
        :disabled="currentPage === totalPages"
        @click="nextPage"
      >
        &gt;
      </button>
      <div class="ticks">
        <div class="tick tick-long"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-medium"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
      </div>
    </div>

    <!-- 6. 最末頁 -->
    <div class="ruler-item">
      <button
        class="control-button page-button last-page"
        :class="{ active: currentPage === totalPages, disabled: currentPage === totalPages }"
        :disabled="currentPage === totalPages || totalPages === 0"
        @click="goToPage(totalPages)"
      >
        &gt;&gt;
      </button>
      <div class="ticks">
        <div class="tick tick-long"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-medium"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
        <div class="tick tick-short"></div>
      </div>
    </div>

    <!-- 結尾長刻度 -->
    <div class="ruler-item end">
      <div class="control-button end-label">
        {{ totalPages || '-' }}
      </div>
      <div class="ticks">
        <div class="tick tick-long"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineProps, defineEmits } from 'vue'

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
.ruler-pagination {
  display: inline-flex;
  align-items: flex-end;
  justify-content: flex-end;
  gap: 0;
  margin: 0;
  padding: 0;
  padding-bottom: 18px;
  padding-left: 20px; /* 給起點標記留出空間 */
  overflow-x: auto;
  user-select: none; /* 禁止選取文字 */
  -webkit-user-select: none; /* Safari */
  -moz-user-select: none; /* Firefox */
  -ms-user-select: none; /* IE10+/Edge */
}

/* 刻度項目容器 */
.ruler-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  /* 每個刻度組寬度 = 9個間距 × 3px + 10條刻度線 × 1px */
  width: calc(27px + 10px);
  margin-right: 3px; /* 組與組之間的間距 */
}

/* 空的刻度項目 */
.ruler-item.empty {
  width: calc(27px + 10px);
}

/* 結尾刻度項目 */
.ruler-item.end {
  width: 20px; /* 增加寬度以容納文字 */
  margin-right: 0; /* 最後一個不需要右邊距 */
}

/* 控制按鈕 */
.control-button {
  position: relative;
  z-index: 10;
  width: 100%;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 500;
  color: var(--neu-text);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  padding: 3px 6px;
  border-radius: 4px;
  margin-bottom: -12px;
  /* 讓按鈕置中對齊第一條長刻度 */
  /* 刻度組寬度37px，長刻度在0.5px處，需要向左移 (37/2 - 0.5) = 18px */
  transform: translateX(-18px);
}

/* 刻度線容器 */
.ticks {
  display: flex;
  align-items: flex-end;
  width: 100%;
  height: 24px;
  position: relative;
}

/* 刻度線基礎樣式 */
.tick {
  width: 1px;
  background: var(--neu-text, #333);
  flex-shrink: 0;
  margin-right: 3px;
}

/* 移除每個刻度組最後一條刻度線的右邊距 */
.ruler-item:not(.end) .tick:last-child {
  margin-right: 0;
}

/* 短刻度 */
.tick-short {
  height: 5px;
}

/* 中長刻度 */
.tick-medium {
  height: 10px;
}

/* 長刻度 */
.tick-long {
  height: 15px;
}

/* 導航按鈕 */
.nav-button {
  font-size: 14px;
  font-weight: 700;
}

/* 當前頁數 */
.current-page {
  font-size: 13px;
  font-weight: 700;
  color: var(--neu-primary);
  /* background: rgba(var(--neu-primary-rgb, 59, 130, 246), 0.1);
  border: 2px solid var(--neu-primary); */
  cursor: default;
}

/* 起點和結尾標記 */
.start-label,
.end-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--neu-text);
  opacity: 0.6;
  cursor: default;
}

/* 起點標記特殊對齊 */
.start-label {
  /* 起點刻度組寬度37px，長刻度在0.5px處 */
  /* 讓文字居中對齊長刻度，需要向左移 (37/2 - 0.5) = 18px */
  transform: translateX(-18px);
}

/* 結尾標記特殊對齊 */
.end-label {
  /* 結尾項目寬度40px，長刻度在0.5px處，文字居中在20px處 */
  /* 需要向左移 (20 - 0.5) = 19.5px */
  transform: translateX(-9.5px);
}

/* 第一頁和最末頁按鈕 */
.first-page,
.last-page {
  font-weight: 600;
}

/* Hover 效果 */
.control-button:hover:not(.disabled):not(.current-page):not(.start-label):not(.end-label) {
  color: var(--neu-primary);
  background: rgba(var(--neu-primary-rgb, 59, 130, 246), 0.08);
}

/* Active 狀態 */
.page-button.active {
  color: var(--neu-primary);
  font-weight: 700;
}

/* 禁用狀態 */
.control-button.disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* 響應式設計 */
@media (max-width: 768px) {
  .ruler-pagination {
    padding: 15px 10px;
    padding-left: 20px; /* 給起點標記留出空間 */
  }

  .ruler-item {
    width: calc(27px + 10px);
    margin-right: 3px;
  }

  .ruler-item.empty {
    width: calc(27px + 10px);
  }

  .ruler-item.end {
    width: 40px; /* 增加寬度以容納文字 */
    margin-right: 0;
  }

  .start-label {
    /* 手機版：向左移動18px讓「0」居中對齊長刻度 */
    transform: translateX(-18px);
  }

  .end-label {
    /* 手機版：結尾項目寬度40px，長刻度在0.5px處，文字居中在20px處 */
    /* 需要向左移 (20 - 0.5) = 19.5px */
    transform: translateX(-19.5px);
  }

  .control-button {
    height: 28px;
    font-size: 11px;
    padding: 4px 6px;
    /* 手機版：刻度組寬度37px，長刻度在0.5px處，需要向左移 (37/2 - 0.5) = 18px */
    transform: translateX(-18px);
  }

  .ticks {
    height: 24px;
  }

  .tick {
    margin-right: 3px;
  }

  .tick-short {
    height: 5px;
  }

  .tick-medium {
    height: 10px;
  }

  .tick-long {
    height: 15px;
  }

  .current-page {
    font-size: 13px;
  }
}
</style>
