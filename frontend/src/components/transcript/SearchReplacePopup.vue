<template>
  <div class="search-replace-popup" ref="popupRef">
    <!-- 搜尋列 -->
    <div class="search-row">
      <div class="search-input-wrapper">
        <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
        </svg>
        <input
          ref="searchInputRef"
          v-model="localSearchText"
          type="text"
          :placeholder="$t('searchReplace.searchPlaceholder')"
          class="search-input"
          @input="handleSearchInput"
          @keydown.enter.prevent="goToNext"
          @keydown.shift.enter.prevent="goToPrevious"
          @keydown.esc="$emit('close')"
        />
        <!-- 搜尋選項按鈕 -->
        <div class="search-options">
          <button
            class="search-option-btn"
            :class="{ active: localMatchCase }"
            @click="toggleMatchCase"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <text x="2" y="17" font-size="15" font-weight="semi-bold" font-family="system-ui, sans-serif">Aa</text>
            </svg>
            <span class="option-tooltip">{{ $t('searchReplace.matchCase') }}</span>
          </button>
          <button
            class="search-option-btn"
            :class="{ active: localMatchWholeWord }"
            @click="toggleMatchWholeWord"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="none">
              <rect x="1" y="5" width="2" height="14" rx="1"/>
              <text x="4.5" y="17" font-size="14" font-weight="semi-bold" font-family="system-ui, sans-serif">ab</text>
              <rect x="22" y="5" width="2" height="14" rx="1"/>
            </svg>
            <span class="option-tooltip">{{ $t('searchReplace.matchWholeWord') }}</span>
          </button>
        </div>
      </div>

      <!-- 結果計數 -->
      <div class="search-results-count" v-if="localSearchText">
        <span v-if="totalMatches > 0">{{ currentMatchIndex + 1 }}/{{ totalMatches }}</span>
        <span v-else class="no-results">{{ $t('searchReplace.noResults') }}</span>
      </div>

      <!-- 上下導航按鈕 -->
      <div class="nav-buttons">
        <button
          class="nav-btn"
          @click="goToPrevious"
          :disabled="totalMatches === 0"
          :title="$t('searchReplace.previous')"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="18 15 12 9 6 15"/>
          </svg>
        </button>
        <button
          class="nav-btn"
          @click="goToNext"
          :disabled="totalMatches === 0"
          :title="$t('searchReplace.next')"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </button>
      </div>

      <!-- 關閉按鈕 -->
      <button class="close-btn" @click="$emit('close')" :title="$t('searchReplace.close')">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>

    <!-- 取代列（僅編輯模式） -->
    <div v-if="isEditing" class="replace-row">
      <div class="replace-input-wrapper">
        <svg class="replace-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M17 1l4 4-4 4"/>
          <path d="M3 11V9a4 4 0 0 1 4-4h14"/>
          <path d="M7 23l-4-4 4-4"/>
          <path d="M21 13v2a4 4 0 0 1-4 4H3"/>
        </svg>
        <input
          v-model="localReplaceText"
          type="text"
          :placeholder="$t('searchReplace.replacePlaceholder')"
          class="replace-input"
          @keydown.enter.prevent="replaceCurrent"
          @keydown.esc="$emit('close')"
        />
      </div>

      <!-- 取代按鈕 -->
      <div class="replace-buttons">
        <button
          class="replace-btn"
          @click="replaceCurrent"
          :disabled="totalMatches === 0 || !localSearchText"
          :title="$t('searchReplace.replaceOne')"
        >
          {{ $t('searchReplace.replace') }}
        </button>
        <button
          class="replace-btn replace-all-btn"
          @click="replaceAll"
          :disabled="totalMatches === 0 || !localSearchText"
          :title="$t('searchReplace.replaceAllTitle')"
        >
          {{ $t('searchReplace.replaceAll') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'

const props = defineProps({
  searchText: {
    type: String,
    default: ''
  },
  replaceText: {
    type: String,
    default: ''
  },
  isEditing: {
    type: Boolean,
    default: false
  },
  totalMatches: {
    type: Number,
    default: 0
  },
  currentMatchIndex: {
    type: Number,
    default: 0
  },
  matchCase: {
    type: Boolean,
    default: false
  },
  matchWholeWord: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits([
  'update:searchText',
  'update:replaceText',
  'update:matchCase',
  'update:matchWholeWord',
  'search',
  'go-to-previous',
  'go-to-next',
  'replace-current',
  'replace-all',
  'close'
])

// Refs
const popupRef = ref(null)
const searchInputRef = ref(null)

// Local state
const localSearchText = ref(props.searchText)
const localReplaceText = ref(props.replaceText)
const localMatchCase = ref(props.matchCase)
const localMatchWholeWord = ref(props.matchWholeWord)

// Debounce timer
let searchDebounceTimer = null

// 處理搜尋輸入
function handleSearchInput() {
  // 清除之前的計時器
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer)
  }

  // 設定新計時器（300ms 延遲）
  searchDebounceTimer = setTimeout(() => {
    emit('update:searchText', localSearchText.value)
    emit('search', localSearchText.value)
  }, 300)
}

// 跳到上一個
function goToPrevious() {
  emit('go-to-previous')
}

// 跳到下一個
function goToNext() {
  emit('go-to-next')
}

// 切換大小寫匹配
function toggleMatchCase() {
  localMatchCase.value = !localMatchCase.value
  emit('update:matchCase', localMatchCase.value)
  // 重新搜尋
  emit('search', localSearchText.value)
}

// 切換全字匹配
function toggleMatchWholeWord() {
  localMatchWholeWord.value = !localMatchWholeWord.value
  emit('update:matchWholeWord', localMatchWholeWord.value)
  // 重新搜尋
  emit('search', localSearchText.value)
}

// 取代當前
function replaceCurrent() {
  emit('update:replaceText', localReplaceText.value)
  emit('replace-current', localReplaceText.value)
}

// 全部取代
function replaceAll() {
  emit('update:replaceText', localReplaceText.value)
  emit('replace-all', localReplaceText.value)
}

// 同步外部 props
watch(() => props.searchText, (val) => {
  localSearchText.value = val
})

watch(() => props.replaceText, (val) => {
  localReplaceText.value = val
})

watch(() => props.matchCase, (val) => {
  localMatchCase.value = val
})

watch(() => props.matchWholeWord, (val) => {
  localMatchWholeWord.value = val
})

// 組件掛載時聚焦搜尋輸入框
onMounted(() => {
  nextTick(() => {
    searchInputRef.value?.focus()
  })
})
</script>

<style scoped>
.search-replace-popup {
  position: fixed;
  top: 70px;
  right: 20px;
  min-width: 480px;
  background: var(--color-white, #ffffff);
  border: 1px solid rgba(163, 177, 198, 0.12);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
  z-index: 1000;
  overflow: visible;
}

/* 搜尋列 */
.search-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(163, 177, 198, 0.1);
  overflow: visible;
}

.search-input-wrapper {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
  overflow: visible;
}

.search-icon {
  position: absolute;
  left: 8px;
  color: var(--main-text-light);
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 6px 68px 6px 32px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 6px;
  background: var(--main-bg);
  color: var(--main-text);
  font-size: 13px;
  transition: border-color 0.2s ease;
}

.search-input:focus {
  outline: none;
  border-color: var(--main-primary);
}

/* 搜尋選項按鈕 */
.search-options {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  gap: 2px;
  overflow: visible;
}

.search-option-btn {
  position: relative;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--main-text-light);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
  overflow: visible;
}

.search-option-btn:hover {
  color: var(--main-text);
}

.search-option-btn.active {
  background: var(--nav-active-bg);
  color: white;
}

.search-option-btn .option-tooltip {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.85);
  color: white;
  border-radius: 4px;
  font-size: 11px;
  white-space: nowrap;
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: opacity 0.15s ease, visibility 0.15s ease;
  z-index: 99999;
}

.search-option-btn .option-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 4px solid transparent;
  border-top-color: rgba(0, 0, 0, 0.85);
}

.search-option-btn:hover .option-tooltip {
  opacity: 1;
  visibility: visible;
}

/* 結果計數 */
.search-results-count {
  font-size: 13px;
  color: var(--main-text-light);
  white-space: nowrap;
  min-width: 50px;
  text-align: center;
}

.search-results-count .no-results {
  color: var(--color-error, #e74c3c);
}

/* 導航按鈕 */
.nav-buttons {
  display: flex;
  gap: 2px;
}

.nav-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--main-text-light);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.nav-btn:hover:not(:disabled) {
  background: var(--main-bg);
  color: var(--main-primary);
}

.nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* 關閉按鈕 */
.close-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--main-text-light);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.close-btn:hover {
  background: rgba(231, 76, 60, 0.1);
  color: var(--color-error, #e74c3c);
}

/* 取代列 */
.replace-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: rgba(163, 177, 198, 0.05);
}

.replace-input-wrapper {
  flex: 1;
  position: relative;
  display: flex;
  align-items: center;
}

.replace-icon {
  position: absolute;
  left: 8px;
  color: var(--main-text-light);
  pointer-events: none;
}

.replace-input {
  width: 100%;
  padding: 6px 10px 6px 32px;
  border: 1px solid rgba(163, 177, 198, 0.3);
  border-radius: 6px;
  background: var(--main-bg);
  color: var(--main-text);
  font-size: 13px;
  transition: border-color 0.2s ease;
}

.replace-input:focus {
  outline: none;
  border-color: var(--main-primary);
}

/* 取代按鈕 */
.replace-buttons {
  display: flex;
  gap: 6px;
}

.replace-btn {
  padding: 6px 12px;
  border: none;
  border-radius: 6px;
  background: var(--main-bg);
  color: var(--main-text);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.replace-btn:hover:not(:disabled) {
  background: var(--main-bg-hover, rgba(163, 177, 198, 0.2));
  color: var(--main-primary);
}

.replace-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.replace-all-btn {
  background: var(--main-primary);
  color: white;
}

.replace-all-btn:hover:not(:disabled) {
  background: var(--main-primary-dark);
  color: white;
}

/* 響應式 */
@media (max-width: 500px) {
  .search-replace-popup {
    min-width: calc(100vw - 24px);
    right: -12px;
  }

  .search-row,
  .replace-row {
    flex-wrap: wrap;
  }

  .search-input-wrapper,
  .replace-input-wrapper {
    min-width: 100%;
  }

  .search-results-count {
    order: 2;
  }

  .nav-buttons {
    order: 3;
  }

  .close-btn {
    order: 1;
    margin-left: auto;
  }

  .replace-buttons {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
