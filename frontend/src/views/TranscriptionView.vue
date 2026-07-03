<template>
  <div class="container">
    <!-- SVG 濾鏡定義 -->
    <ElectricBorder />

    <!-- 上傳進行中提示：另一批上傳（可能在別頁啟動）尚未完成，暫時鎖住新上傳，
         避免單槽位的 uploadStore 被新 start() 覆蓋掉進度 / 孤兒化前一批的 AbortController -->
    <div v-if="uploadStore.busy && !uploading" class="upload-busy-hint">
      {{ $t('uploadZone.busyHint') }}
    </div>

    <!-- 上傳區域（含三角形合併按鈕） -->
    <UploadZone
      @file-selected="handleFileUpload"
      @files-selected="handleFilesUpload"
      @open-merge="openMergeModal"
      @open-tour="launchTourManually"
      :uploading="uploading"
      :disabled="uploadStore.busy || !!pendingFile || mergeMode.isActive || batchMode.isActive"
    />

    <!-- 合併對話窗 -->
    <MergeModal
      :visible="showMergeModal"
      @close="closeMergeModal"
      @confirm="handleMergeConfirm"
    />

    <!-- 批次上傳跳窗 -->
    <BatchUploadModal
      :visible="batchMode.isActive"
      :initial-files="batchMode.files"
      :existing-tags="allTags"
      @close="cancelBatchUpload"
      @submit="confirmBatchUpload"
    />

    <!-- 轉錄設定跳窗（單檔上傳 / 合併皆共用） -->
    <TaskSettingsModal
      :visible="!!pendingFile || mergeMode.showForm"
      :is-merge-mode="mergeMode.isActive"
      :pending-file="pendingFile"
      :merge-files="mergeMode.files"
      :default-merge-task-name="defaultMergeTaskName"
      :all-tags="allTags"
      :dismissible="!tourMode"
      v-model:task-type="taskType"
      v-model:language="selectedLanguage"
      v-model:diarize="enableDiarization"
      v-model:max-speakers="maxSpeakers"
      v-model:tags="selectedTags"
      v-model:tag-input="tagInput"
      v-model:merge-task-name="mergeTaskName"
      @close="cancelUpload"
      @confirm="confirmAndUpload"
    />

  </div>

</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import ElectricBorder from '../components/shared/ElectricBorder.vue'
import UploadZone from '../components/UploadZone.vue'
import MergeModal from '../components/merge/MergeModal.vue'
import TaskSettingsModal from '../components/transcription/TaskSettingsModal.vue'
import BatchUploadModal from '../components/batch/BatchUploadModal.vue'

// 新 API 服務層
import { transcriptionService, taskService } from '../api/services'
import { exceedsMaxSize, MAX_UPLOAD_SIZE_MB } from '../utils/chunkedUpload.js'
import { useProductTour } from '../composables/useProductTour'
import { useTaskTags } from '../composables/task/useTaskTags'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useUploadStore } from '../stores/upload'
import { useTourStore, TOUR_PHASES, TOUR_ANCHORS, tourSel } from '../stores/tour'
import { quotaErrorFromDetail } from '../utils/quotaError'
import { errorI18n } from '../utils/apiError'

const { t: $t, locale } = useI18n()
const router = useRouter()
const { tagsData, fetchTagColors } = useTaskTags($t)

const authStore = useAuthStore()
const uiStore = useUiStore()
const uploadStore = useUploadStore()

const showNotification = inject('showNotification')

// 上傳完成 toast 的「查看」動作：導向任務列表。
// 已在任務列表頁時 router.push 同路由會被忽略 → 改整頁重整，確保新任務刷新出現。
function goToTasks() {
  if (router.currentRoute.value.name === 'tasks') {
    window.location.reload()
    return
  }
  router.push({ name: 'tasks' })
}

const uploading = ref(false)
const uploadProgress = ref(0) // 分片上傳進度 0-100
const taskType = ref('paragraph')  // 任務類型：paragraph（段落）或 subtitle（字幕）
const selectedLanguage = ref('auto')
const enableDiarization = ref(true)
const maxSpeakers = ref(null)
const pendingFile = ref(null)
const selectedTags = ref([])
const tagInput = ref('')

// 新手導覽（方案 C）：導覽期間用 demo 檔展開設定表單；tourMode 攔截送出，永不上傳
const tour = useProductTour()
const tourStore = useTourStore()
const tourMode = ref(false)

// 合併模式狀態
const mergeMode = reactive({
  isActive: false,      // 是否處於合併模式
  showForm: false,      // 是否顯示轉錄設定表單
  files: []             // 待合併的檔案列表
})
const mergeTaskName = ref('')
const showMergeModal = ref(false)  // 合併對話窗顯示狀態

// 批次模式狀態
const batchMode = reactive({
  isActive: false,      // 是否處於批次模式
  files: []             // 待上傳的檔案列表
})

// 預設任務名稱（第一個檔案的檔名，去掉副檔名）
const defaultMergeTaskName = computed(() => {
  if (mergeMode.files.length > 0) {
    const firstName = mergeMode.files[0].name
    return firstName.replace(/\.[^/.]+$/, '')  // 去掉副檔名
  }
  return ''
})

// 格式化檔案大小
function formatFileSize(bytes) {
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

// 是否為使用者主動取消（axios CanceledError）—— 不應彈錯誤通知
function isUploadCancelled(error) {
  return (
    uploadStore.status === 'cancelled' ||
    error?.code === 'ERR_CANCELED' ||
    error?.name === 'CanceledError'
  )
}

// 獲取所有唯一標籤（canonical 來源：/tags，包含尚未被任何 task 使用的孤兒 tag）
// 傳給 TaskSettingsModal（快速標籤）與 BatchUploadModal
const allTags = computed(() => tagsData.value.map(t => t.name))

// 過濾超過單檔上限的檔案，彈出提示；回傳允許上傳的檔案
function filterOversizedFiles(files) {
  const oversized = files.filter(exceedsMaxSize)
  if (oversized.length > 0 && showNotification) {
    showNotification({
      title: $t('uploadZone.fileTooLarge'),
      message:
        oversized.length === 1
          ? $t('uploadZone.fileTooLargeMessage', {
              name: oversized[0].name,
              size: formatFileSize(oversized[0].size),
              max: MAX_UPLOAD_SIZE_MB,
            })
          : $t('uploadZone.filesTooLargeMessage', {
              count: oversized.length,
              max: MAX_UPLOAD_SIZE_MB,
            }),
      type: 'warning',
    })
  }
  return files.filter((f) => !exceedsMaxSize(f))
}

// 選擇檔案後顯示確認表單（單檔）
function handleFileUpload(file) {
  if (filterOversizedFiles([file]).length === 0) return
  pendingFile.value = file
}

// 選擇多個檔案後進入批次模式
function handleFilesUpload(files) {
  if (!files || files.length === 0) return

  // 方案功能檢查：批次上傳僅 Basic 以上方案可用（後端亦會強制擋下）
  if (!authStore.quota?.features?.batch_operations) {
    uiStore.showQuotaModal('batch_operations')
    return
  }

  files = filterOversizedFiles(files)
  if (files.length === 0) return

  // 檢查檔案數量上限
  const MAX_BATCH_FILES = 10
  if (files.length > MAX_BATCH_FILES) {
    if (showNotification) {
      showNotification({
        title: $t('batchUpload.tooManyFiles'),
        message: $t('batchUpload.maxFilesMessage', { max: MAX_BATCH_FILES, count: files.length }),
        type: 'warning'
      })
    }
    // 只取前 10 個檔案
    batchMode.files = files.slice(0, MAX_BATCH_FILES)
  } else {
    batchMode.files = files
  }

  batchMode.isActive = true
}

// 標籤管理（新增/移除/快速標籤）已移入 TaskSettingsModal，透過 v-model:tags 回寫 selectedTags

// 確認後開始上傳
async function confirmAndUpload() {
  // 導覽展示模式：demo 檔不可真的送出（否則會建立垃圾任務、扣配額）。核心防呆。
  if (tourMode.value) return

  // 判斷是合併模式還是單檔模式
  const isMergeMode = mergeMode.isActive && mergeMode.files.length > 0

  if (!isMergeMode && !pendingFile.value) return

  uploading.value = true

  const formData = new FormData()

  if (isMergeMode) {
    // 合併模式：添加所有檔案
    mergeMode.files.forEach((file) => {
      formData.append('files', file)
    })
    formData.append('merge_files', 'true')

    // 添加自訂任務名稱（如果有）
    const finalTaskName = mergeTaskName.value.trim() || defaultMergeTaskName.value
    if (finalTaskName) {
      formData.append('custom_name', finalTaskName)
    }
  } else {
    // 單檔模式
    formData.append('file', pendingFile.value)
  }

  // 共用的轉錄設定
  formData.append('task_type', taskType.value)
  formData.append('punct_provider', 'gemini')
  formData.append('chunk_audio', 'true')
  formData.append('language', selectedLanguage.value)
  formData.append('ui_language', locale.value)
  formData.append('diarize', enableDiarization.value ? 'true' : 'false')
  if (enableDiarization.value && maxSpeakers.value) {
    formData.append('max_speakers', maxSpeakers.value.toString())
  }
  if (selectedTags.value.length > 0) {
    formData.append('tags', JSON.stringify(selectedTags.value))
  }

  // 先擷取顯示用資訊：上傳可能在使用者離開本頁後才完成，屆時 pendingFile/mergeMode 已重置
  const displayName = isMergeMode
    ? $t('globalUpload.mergeLabel', { count: mergeMode.files.length })
    : pendingFile.value.name

  // 全域上傳看板：跳頁也持續顯示進度
  uploadStore.start({ kind: isMergeMode ? 'merge' : 'single', label: displayName })

  // 送出即關窗：上傳改由全域浮層顯示進度、完成走 toast，避免使用者被遮罩卡在跳窗後。
  // formData 已組好、displayName 已擷取，後續流程不再讀這些狀態。finally 仍會再 reset（冪等）。
  pendingFile.value = null
  mergeMode.isActive = false
  mergeMode.showForm = false
  mergeMode.files = []

  try {
    // 使用新 API 服務層（大檔自動走分片上傳）
    uploadProgress.value = 0
    await transcriptionService.create(formData, {
      signal: uploadStore.getSignal(),
      onProgress: (pct) => {
        uploadProgress.value = pct
        uploadStore.setProgress(pct)
      }
    })

    // 上傳完成 → 收掉上傳中浮層，終態統一走 toast
    uploadStore.succeed()

    // 完成通知（帶「查看」動作）。使用者上傳途中切去別頁時不會自動跳轉，
    // 這顆按鈕是他直達新任務的唯一入口。
    if (showNotification) {
      showNotification({
        title: $t('globalUpload.statusDone'),
        type: 'success',
        action: { label: $t('globalUpload.view'), handler: goToTasks },
      })
    }

    // 轉錄已建立，若使用者仍在上傳頁則自動跳轉到任務列表；
    // 已離開本頁則不強拉回來，改由 toast 的「查看」按鈕引導
    if (router.currentRoute.value.name === 'transcription') {
      router.push({ name: 'tasks' })
    }
  } catch (error) {
    // 使用者主動取消：不視為錯誤，看板已標記 cancelled
    if (isUploadCancelled(error)) {
      // no-op
    } else {
      console.error($t('transcription.errorUpload') + ':', error)
      const detail = error.response?.data?.detail
      const errorMsg = uploadErrorMessage(error)
      uploadStore.fail(errorMsg)  // 收掉上傳中浮層
      // 終態統一走 toast（浮層只負責上傳中）；額度不足改用引導購買對話框
      const quota = quotaErrorFromDetail(detail)
      if (quota) {
        uiStore.showQuotaModal(quota.type)
      } else if (showNotification) {
        showNotification({
          title: $t('transcription.uploadFailed'),
          message: errorMsg,
          type: 'error'
        })
      }
    }
  } finally {
    uploading.value = false
    uploadProgress.value = 0
    pendingFile.value = null
    taskType.value = 'paragraph'  // 重置為預設值
    selectedTags.value = []
    tagInput.value = ''
    // 重置合併模式
    mergeMode.isActive = false
    mergeMode.showForm = false
    mergeMode.files = []
    mergeTaskName.value = ''
  }
}

// 把上傳錯誤轉成「跟隨 UI 語言」的訊息：
//  - 已知結構化 code（如 FEATURE_NOT_AVAILABLE）→ 前端 i18n
//  - 網路 / JS 錯誤（無後端 detail）→ 通用 i18n（取代原本會漏出的英文 library 字串）
//  - 其餘後端訊息（語言由後端決定）→ 沿用（完整 localize 需後端 i18n）
function uploadErrorMessage(error) {
  return detailToMessage(error?.response?.data?.detail)
}

// 把後端 detail 本體（字串 或 {code,message,params} 物件）轉成跟隨 UI 語言的訊息。
// 經集中對照（apiError.ts）：有 code 對應 i18n key → 前端翻譯（多語系）；
// 否則 fallback 到後端 message（中文）；再不然通用錯誤。
// 共用給「axios error」與「批次回傳 tasks[].error 的裸 detail」。
function detailToMessage(detail) {
  const { key, params, fallback } = errorI18n(detail)
  if (key) return $t(key, params)
  return fallback || $t('uploadErrors.generic')
}

// 取消上傳
function cancelUpload() {
  // 上傳進行中 → 真正中斷請求（與 toast 的 uploadStore.cancel 一致）；非上傳中則僅重置表單
  if (uploading.value) uploadStore.cancel()
  pendingFile.value = null
  taskType.value = 'paragraph'  // 重置為預設值
  selectedTags.value = []
  tagInput.value = ''
  // 也重置合併模式
  mergeMode.isActive = false
  mergeMode.showForm = false
  mergeMode.files = []
  mergeTaskName.value = ''
}

// 開啟合併對話窗
function openMergeModal() {
  showMergeModal.value = true
}

// 關閉合併對話窗
function closeMergeModal() {
  showMergeModal.value = false
}

// 處理合併對話窗確認（進入轉錄設定表單）
function handleMergeConfirm(files) {
  closeMergeModal()
  const allowed = filterOversizedFiles(files)
  if (allowed.length < 2) return  // 合併至少需 2 個檔案
  handleShowTranscriptionForm(allowed)
}

// 處理「進入轉錄設定」（合併模式）
function handleShowTranscriptionForm(files) {
  mergeMode.isActive = true
  mergeMode.showForm = true
  mergeMode.files = files
  mergeTaskName.value = ''  // 重置任務名稱
}

// 取消批次上傳
function cancelBatchUpload() {
  // 上傳進行中 → 真正中斷請求（與 toast 一致）；非上傳中則僅關面板
  if (uploading.value) uploadStore.cancel()
  batchMode.isActive = false
  batchMode.files = []
}

// 確認批次上傳
async function confirmBatchUpload(formData) {
  uploading.value = true
  uploadProgress.value = 0
  const batchFileCount = formData.getAll('files').length

  // 全域上傳看板（批次）
  uploadStore.start({
    kind: 'batch',
    label: $t('globalUpload.batchLabel', { count: batchFileCount }),
    batchTotal: batchFileCount,
  })

  // 送出即關窗：批次進度（含 N/總）改由全域浮層顯示，避免使用者被遮罩卡住。
  // formData 已組好，後續流程不再讀 batchMode。finally 的 cancelBatchUpload 會再 reset（冪等）。
  batchMode.isActive = false
  batchMode.files = []

  try {
    const result = await transcriptionService.createBatch(formData, {
      signal: uploadStore.getSignal(),
      onProgress: (pct) => {
        uploadProgress.value = pct
        uploadStore.setProgress(pct)
      },
      onFileProgress: (current, total) => {
        uploadStore.setFileProgress(current, total)
      }
    })

    uploadStore.succeed()

    // 若有檔案因額度不足失敗，開啟引導購買對話框
    const batchQuota = (result.tasks || []).map(t => quotaErrorFromDetail(t.error)).find(Boolean)
    if (batchQuota) {
      uiStore.showQuotaModal(batchQuota.type)
    }

    // 顯示結果通知
    if (showNotification) {
      if (result.failed > 0) {
        // 列出哪些檔失敗、各自原因（後端在 tasks[].error 帶了 detail，先前只用來
        // 判斷配額 Modal，沒告知使用者明細）。上限 5 筆避免 toast 過長。
        const FAILED_LIST_MAX = 5
        const failedLines = (result.tasks || [])
          .filter(t => t.error)
          .map(t => $t('batchUpload.failedItem', {
            filename: t.filename,
            reason: detailToMessage(t.error),
          }))
        const shown = failedLines.slice(0, FAILED_LIST_MAX)
        if (failedLines.length > FAILED_LIST_MAX) {
          shown.push($t('batchUpload.moreFailures', { count: failedLines.length - FAILED_LIST_MAX }))
        }
        showNotification({
          title: $t('batchUpload.partialSuccess'),
          message: [
            $t('batchUpload.partialSuccessMessage', { created: result.created, failed: result.failed }),
            ...shown,
          ].join('\n'),
          type: 'warning',
          // 仍有任務建立成功 → 提供「查看」直達（部分失敗不會自動跳轉）
          action: result.created > 0 ? { label: $t('globalUpload.view'), handler: goToTasks } : undefined,
        })
      } else {
        showNotification({
          title: $t('batchUpload.success'),
          message: $t('batchUpload.successMessage', { count: result.created }),
          type: 'success',
          action: { label: $t('globalUpload.view'), handler: goToTasks },
        })
      }
    }

    // 上傳完成後重抓 tag 列表（user 可能在 BatchUploadModal 內建了新 tag）
    await fetchTagColors()

    // 全部成功且未觸發額度購買 Modal → 跳轉任務列表（與單檔上傳一致）；
    // 部分失敗或彈了購買引導則留在原頁，避免把引導/失敗結果蓋掉
    if (result.failed === 0 && !batchQuota && router.currentRoute.value.name === 'transcription') {
      router.push({ name: 'tasks' })
    }

  } catch (error) {
    // 使用者主動取消：不視為錯誤
    if (!isUploadCancelled(error)) {
      console.error('批次上傳失敗:', error)
      const errorMsg = uploadErrorMessage(error)
      uploadStore.fail(errorMsg)  // 收掉上傳中浮層；終態統一走 toast
      if (showNotification) {
        showNotification({
          title: $t('batchUpload.failed'),
          message: errorMsg,
          type: 'error'
        })
      }
    }
  } finally {
    uploading.value = false
    uploadProgress.value = 0
    cancelBatchUpload()
  }
}

// === 新手導覽（方案 C）===

// 純導覽展示用的佔位檔；tourMode 會攔截送出，永不上傳。
// 配置一個合理大小的 buffer 讓檔案資訊區顯示像樣的容量（導覽結束即釋放）。
function makeDemoFile() {
  const bytes = new Uint8Array(2_517_000) // ≈ 2.40 MB
  return new File([bytes], $t('tour.demoFileName'), { type: 'audio/mpeg' })
}

// 導覽結束（完成 / 略過 / 關閉）→ 還原表單到乾淨初始狀態
function endTour() {
  tourMode.value = false
  pendingFile.value = null
  taskType.value = 'paragraph'
  selectedLanguage.value = 'auto'
  enableDiarization.value = true
  maxSpeakers.value = null
  selectedTags.value = []
  tagInput.value = ''
}

// 導覽：離開「上傳區」步 → 展開示範設定跳窗，待 Teleport DOM ready 再前進到跳窗內步驟。
// 跳窗有遮罩，若一開始就展開會蓋住歡迎步與上傳區錨點，故延後到此刻才開。
async function openDemoFormThenNext() {
  pendingFile.value = makeDemoFile()
  await nextTick() // 等 TaskSettingsModal（Teleport→body）渲染，data-tour 錨點才存在
  // 跳窗有 0.3s slideUp 進場動畫。若立刻 moveNext，driver 會在動畫/版面未定時就用舊 rect
  // 定位 ④（task-type 高區塊），造成 popover 甩到螢幕左上角、與 spotlight 脫開。
  // 改為等動畫 settle 後再 moveNext，讓 driver 一次就用最終 rect 把 popover 定在卡片正下方。
  // 延遲取 360ms > 動畫 300ms；timeout 內重新取得 driver（使用者中途關閉導覽時 getDriver() 回 null）。
  setTimeout(() => tour.getDriver()?.moveNext(), 360)
}

// 導覽：從跳窗第一步（任務類型）返回「上傳區」→ 收起跳窗，讓上傳區錨點重新可被高亮
async function closeDemoFormThenPrev() {
  pendingFile.value = null
  await nextTick()
  tour.getDriver()?.movePrevious()
}

// 跳窗內容可能超過視窗高度而內捲（modal-body overflow）。導覽高亮前先把錨點捲進
// 可視區，否則 driver 以 window 判斷「可見」會把 spotlight 畫在被裁切的位置（看似沒對到）。
function scrollAnchorIntoView(el) {
  el?.scrollIntoView?.({ block: 'center', behavior: 'auto' })
}

// 跳窗內步驟順序對齊新版單欄排版（由上到下）：任務類型 → 語言 → 說話者辨識 → 開始
function buildTourSteps() {
  return [
    {
      // 歡迎步：無錨點 → 置中 popover，導覽開始前先說明（跳窗此時仍關閉）
      popover: {
        title: $t('tour.welcome.title'),
        description: $t('tour.welcome.desc'),
        nextBtnText: $t('tour.welcome.start'),
        showButtons: ['next', 'close'],
      },
    },
    {
      // 上傳區：跳窗仍關閉，按「下一步」才展開示範跳窗
      element: tourSel(TOUR_ANCHORS.UPLOAD),
      popover: {
        title: $t('tour.upload.title'),
        description: $t('tour.upload.desc'),
        onNextClick: openDemoFormThenNext,
      },
    },
    {
      element: tourSel(TOUR_ANCHORS.TASK_TYPE),
      onHighlightStarted: scrollAnchorIntoView,
      popover: {
        // task-type 是彈窗內最高的區塊；固定 popover 於卡片下方（下方空間最充足），
        // 避免 driver 預設側邊放不下時把 popover 甩到螢幕左上角、與 spotlight 脫開。
        side: 'bottom',
        align: 'center',
        title: $t('tour.taskType.title'),
        description: $t('tour.taskType.desc'),
        onPrevClick: closeDemoFormThenPrev,
      },
    },
    {
      element: tourSel(TOUR_ANCHORS.LANGUAGE),
      onHighlightStarted: scrollAnchorIntoView,
      popover: { title: $t('tour.language.title'), description: $t('tour.language.desc') },
    },
    {
      element: tourSel(TOUR_ANCHORS.DIARIZE),
      onHighlightStarted: scrollAnchorIntoView,
      popover: { title: $t('tour.diarize.title'), description: $t('tour.diarize.desc') },
    },
    {
      // 上傳 phase 最後一步：交棒到任務列表 phase
      element: tourSel(TOUR_ANCHORS.START),
      popover: {
        title: $t('tour.start.title'),
        description: $t('tour.start.desc'),
        doneBtnText: $t('tour.toList'),
        onNextClick: () => tour.advanceTo(tourStore, router, TOUR_PHASES.LIST, '/all'),
      },
    },
  ]
}

// 是否處於「不該啟動導覽」的忙碌狀態（上傳中／表單填寫中／合併／批次）——
// 導覽過程會設 demo pendingFile，這些狀態下會覆蓋使用者正在進行的操作。
const tourLaunchBlocked = computed(
  () => uploadStore.busy || !!pendingFile.value || mergeMode.isActive || batchMode.isActive
)

// 實際啟動導覽（自動與手動共用）。歡迎步與上傳區步在跳窗關閉下進行，
// 故此處不展開跳窗（改由 openDemoFormThenNext 在離開上傳區時才展開）。
function beginTour() {
  tourStore.start() // phase = 'upload'
  tourMode.value = true
  // 換頁到列表 phase 時不收尾；使用者關閉則還原表單並結束導覽
  tour.run({
    steps: buildTourSteps(),
    t: $t,
    onDestroyed: tour.makeDestroyHandler(tourStore, endTour),
  })
}

// 自動觸發：僅對「零任務新使用者、未看過、非行動裝置、不忙碌」
async function maybeStartTour() {
  if (tourStore.hasSeen() || tour.isMobile() || tourLaunchBlocked.value) return

  let total = 0
  try {
    ;({ total } = await taskService.list({ limit: 1, skip: 0 }))
  } catch {
    return // 查詢失敗：不打擾，靜默略過
  }
  if (total >= 1) return

  beginTour()
}

// 手動觸發（上傳頁「查看使用教學」連結）：略過 hasSeen / 零任務 gating，
// 讓既有使用者也能重看；但仍避開忙碌狀態以免覆蓋進行中的操作。
function launchTourManually() {
  if (tourLaunchBlocked.value) return
  beginTour()
}

// 生命週期
onMounted(() => {
  fetchTagColors()  // 取得 canonical tag 列表（含尚未被使用的孤兒 tag）
  // 限制視窗高度
  document.body.classList.add('upload-page')
  maybeStartTour()
})

onUnmounted(() => {
  // 離開頁面時若導覽仍在跑，強制收掉避免殘留 overlay
  tour.getDriver()?.destroy?.()
  // 清理：移除視窗高度限制
  document.body.classList.remove('upload-page')
})
</script>

<style scoped>
.container {
  animation: fadeIn 0.5s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 上傳進行中提示橫幅 */
.upload-busy-hint {
  max-width: 800px;
  margin: 16px auto 0;
  padding: 12px 16px;
  border-radius: 8px;
  background: rgba(221, 132, 72, 0.1);
  border: 1px solid var(--electric-primary, #dd8448);
  color: var(--main-text);
  font-size: 14px;
  text-align: center;
}

@media (max-width: 480px) {
  .container {
    padding: 0 8px;
  }
}
</style>

<!-- driver.js popover 主題（非 scoped：popover 掛在 body 外層，scoped 屬性選不到）-->
<style>
.driver-popover.sl-tour-popover {
  background: var(--main-bg, #e0e5ec);
  color: var(--main-text, #4a5568);
  border-radius: 14px;
  box-shadow:
    6px 6px 14px var(--main-shadow-dark, rgba(163, 177, 198, 0.6)),
    -6px -6px 14px var(--main-shadow-light, rgba(255, 255, 255, 0.8));
  max-width: 320px;
}

.driver-popover.sl-tour-popover .driver-popover-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--main-text, #4a5568);
}

.driver-popover.sl-tour-popover .driver-popover-description {
  font-size: 13px;
  line-height: 1.65;
  color: rgba(var(--color-text-dark-rgb, 74, 85, 104), 0.75);
}

.driver-popover.sl-tour-popover .driver-popover-progress-text {
  font-size: 12px;
  color: rgba(var(--color-text-dark-rgb, 74, 85, 104), 0.5);
}

/* ✕ 關閉鈕：用會隨深/淺色主題翻轉的色票（driver 預設 #d2d2d2/hover #2d2d2d 在深色下會隱形）*/
.driver-popover.sl-tour-popover .driver-popover-close-btn {
  color: rgba(var(--color-text-dark-rgb, 74, 85, 104), 0.6);
}

.driver-popover.sl-tour-popover .driver-popover-close-btn:hover,
.driver-popover.sl-tour-popover .driver-popover-close-btn:focus {
  color: var(--main-text, #4a5568);
}

.driver-popover.sl-tour-popover .driver-popover-next-btn {
  /* 用 electric-primary（深淺色都是品牌橘）；--main-primary 在深色模式會變灰藍 */
  background: var(--electric-primary, #dd8448);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  text-shadow: none;
}

/* 蓋掉 driver 預設 hover(#f7f7f7 會把按鈕變淺灰)，維持品牌橘 */
.driver-popover.sl-tour-popover .driver-popover-next-btn:hover,
.driver-popover.sl-tour-popover .driver-popover-next-btn:focus {
  background: var(--electric-primary, #dd8448);
  color: #fff;
  filter: brightness(1.06);
}

.driver-popover.sl-tour-popover .driver-popover-prev-btn {
  background: transparent;
  color: rgba(var(--color-text-dark-rgb, 74, 85, 104), 0.7);
  border: 1px solid rgba(var(--color-text-dark-rgb, 74, 85, 104), 0.2);
  border-radius: 8px;
  text-shadow: none;
}

/* 蓋掉 driver 預設 hover(#f7f7f7 在深色下會讓淺色字看不見) */
.driver-popover.sl-tour-popover .driver-popover-prev-btn:hover,
.driver-popover.sl-tour-popover .driver-popover-prev-btn:focus {
  background: rgba(var(--color-text-dark-rgb, 74, 85, 104), 0.08);
  color: var(--main-text, #4a5568);
}

/* 隱藏 popover 指向箭頭（小白色三角條塊） */
.driver-popover.sl-tour-popover .driver-popover-arrow {
  display: none !important;
}
</style>
