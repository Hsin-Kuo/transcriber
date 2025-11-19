<template>
  <div class="container">
    <!-- SVG 濾鏡定義 -->
    <ElectricBorder />

    <header class="header">
      <h1>🎙️ Whisper Transcription Service</h1>
      <p>Upload audio files for automatic transcription with punctuation</p>
    </header>

    <!-- 上傳區域 -->
    <UploadZone @file-selected="handleFileUpload" :uploading="uploading" />

    <!-- 確認對話框 -->
    <div v-if="showConfirmDialog" class="modal-overlay" @click.self="cancelUpload">
      <div class="modal-content electric-card">
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main modal-body">
              <!-- 檔案資訊 -->
              <div class="modal-section">
                <div class="file-info">
                  <span class="label">檔案名稱</span>
                  <span class="value">{{ pendingFile?.name }}</span>
                </div>
                <div class="file-info" v-if="pendingFile">
                  <span class="label">檔案大小</span>
                  <span class="value">{{ (pendingFile.size / 1024 / 1024).toFixed(2) }} MB</span>
                </div>
              </div>

              <!-- 轉錄語言 -->
              <div class="modal-section">
                <label class="section-label">轉錄語言</label>
                <select id="language" v-model="selectedLanguage" class="select-input">
                  <option value="auto">自動偵測</option>
                  <option value="zh">中文</option>
                  <option value="en">English</option>
                  <option value="ja">日本語</option>
                  <option value="ko">한국어</option>
                </select>
              </div>

              <!-- 說話者辨識 -->
              <div class="modal-section">
                <label class="section-label">說話者辨識</label>

                <div class="checkbox-item">
                  <input type="checkbox" id="modal-diarize" v-model="enableDiarization" />
                  <label for="modal-diarize">啟用</label>
                </div>

                <div class="sub-setting" v-if="enableDiarization">
                  <label for="modal-maxSpeakers" class="sub-label">
                    最大講者人數
                    <span class="hint">可提高精確度，避免過度分析。留空則自動偵測，</span>
                  </label>
                  <input
                    type="number"
                    id="modal-maxSpeakers"
                    v-model.number="maxSpeakers"
                    min="2"
                    max="10"
                    placeholder="自動偵測"
                    class="number-input"
                  />
                </div>
              </div>

              <!-- 動作按鈕 -->
              <div class="modal-actions">
                <button class="btn btn-secondary" @click="cancelUpload">取消</button>
                <button class="btn btn-primary" @click="confirmAndUpload">開始轉錄</button>
              </div>
            </div>
          </div>
          <div class="electric-glow-1"></div>
          <div class="electric-glow-2"></div>
        </div>
        <div class="electric-overlay"></div>
        <div class="electric-bg-glow"></div>
      </div>
    </div>

    <!-- 統計面板 -->
    <div class="stats-panel" v-if="tasks.length > 0">
      <div class="stat-item">
        <span class="stat-label">Total Tasks</span>
        <span class="stat-value">{{ tasks.length }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Active</span>
        <span class="stat-value">{{ activeTasks }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Completed</span>
        <span class="stat-value">{{ completedTasks }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">Failed</span>
        <span class="stat-value">{{ failedTasks }}</span>
      </div>
    </div>

    <!-- 任務列表 -->
    <TaskList
      :tasks="tasks"
      @download="downloadTask"
      @refresh="refreshTasks"
      @delete="deleteTask"
      @cancel="cancelTask"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import ElectricBorder from './components/ElectricBorder.vue'
import UploadZone from './components/UploadZone.vue'
import TaskList from './components/TaskList.vue'

// 統一使用 /api，由 Vite dev server 或 Nginx 代理到後端
const API_BASE = '/api'

const tasks = ref([])
const uploading = ref(false)
const enableDiarization = ref(true)
const maxSpeakers = ref(null)
const showConfirmDialog = ref(false)
const pendingFile = ref(null)
const selectedLanguage = ref('zh')
let pollInterval = null

// 統計數據
const activeTasks = computed(() =>
  tasks.value.filter(t => ['pending', 'processing'].includes(t.status)).length
)
const completedTasks = computed(() =>
  tasks.value.filter(t => t.status === 'completed').length
)
const failedTasks = computed(() =>
  tasks.value.filter(t => t.status === 'failed').length
)

// 選擇檔案後顯示確認對話框
function handleFileUpload(file) {
  pendingFile.value = file
  showConfirmDialog.value = true
}

// 確認後開始上傳
async function confirmAndUpload() {
  if (!pendingFile.value) return

  showConfirmDialog.value = false
  uploading.value = true

  const formData = new FormData()
  formData.append('file', pendingFile.value)
  formData.append('punct_provider', 'gemini')
  formData.append('chunk_audio', 'true')
  formData.append('language', selectedLanguage.value)
  formData.append('diarize', enableDiarization.value ? 'true' : 'false')
  if (enableDiarization.value && maxSpeakers.value) {
    formData.append('max_speakers', maxSpeakers.value.toString())
  }

  try {
    const response = await axios.post(`${API_BASE}/transcribe`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })

    const newTask = {
      ...response.data,
      file: pendingFile.value.name,
      uploadedAt: new Date().toLocaleString('zh-TW')
    }

    tasks.value.unshift(newTask)
    startPolling()
  } catch (error) {
    console.error('上傳失敗:', error)
    alert('上傳失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    uploading.value = false
    pendingFile.value = null
  }
}

// 取消上傳
function cancelUpload() {
  showConfirmDialog.value = false
  pendingFile.value = null
}

// 輪詢更新任務狀態
async function pollTaskStatus(task) {
  if (!['pending', 'processing'].includes(task.status) && !task.cancelling) return

  try {
    const response = await axios.get(`${API_BASE}/transcribe/${task.task_id}`)
    // 保存 cancelling 狀態，避免被伺服器回應覆蓋
    const cancelling = task.cancelling
    Object.assign(task, response.data)

    // 如果任務正在取消中，只有當後端狀態變成 cancelled 時才清除 cancelling
    if (cancelling && response.data.status === 'cancelled') {
      task.cancelling = false
      console.log('任務已完全停止:', task.task_id)
    } else if (cancelling) {
      task.cancelling = true
    }
  } catch (error) {
    console.error('獲取任務狀態失敗:', error)
  }
}

// 開始輪詢
function startPolling() {
  if (pollInterval) return

  pollInterval = setInterval(() => {
    const activeTasks = tasks.value.filter(t =>
      ['pending', 'processing'].includes(t.status) || t.cancelling
    )

    if (activeTasks.length === 0) {
      stopPolling()
      return
    }

    activeTasks.forEach(task => pollTaskStatus(task))
  }, 2000) // 每 2 秒輪詢一次
}

// 停止輪詢
function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

// 下載結果
async function downloadTask(taskId) {
  try {
    const response = await axios.get(`${API_BASE}/transcribe/${taskId}/download`, {
      responseType: 'blob'
    })

    const task = tasks.value.find(t => t.task_id === taskId)
    const filename = task?.result_filename || 'transcript.txt'

    const url = window.URL.createObjectURL(new Blob([response.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('下載失敗:', error)
    alert('下載失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 取消任務
async function cancelTask(taskId) {
  if (!confirm('確定要取消此任務嗎？任務將停止執行，暫存檔案將被刪除。')) {
    return
  }

  // 找到任務並設置取消中狀態
  const task = tasks.value.find(t => t.task_id === taskId)
  if (task) {
    task.cancelling = true
  }

  try {
    await axios.post(`${API_BASE}/transcribe/${taskId}/cancel`)

    console.log('任務取消指令已發送:', taskId)

    // 不要立即設置狀態，讓輪詢來更新
    // 當後端真正停止時，輪詢會獲取到 cancelled 狀態
    // 此時 pollTaskStatus 會清除 cancelling 標記
  } catch (error) {
    console.error('取消失敗:', error)
    if (task) {
      task.cancelling = false
    }
    alert('取消失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 刪除任務
async function deleteTask(taskId) {
  if (!confirm('確定要刪除此任務及其檔案嗎？此操作無法復原。')) {
    return
  }

  try {
    await axios.delete(`${API_BASE}/transcribe/${taskId}`)

    // 從本地列表中移除
    const index = tasks.value.findIndex(t => t.task_id === taskId)
    if (index !== -1) {
      tasks.value.splice(index, 1)
    }

    console.log('任務已刪除:', taskId)
  } catch (error) {
    console.error('刪除失敗:', error)
    alert('刪除失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 刷新所有任務
async function refreshTasks() {
  try {
    const response = await axios.get(`${API_BASE}/transcribe/active/list`)
    const serverTasks = response.data.all_tasks || []

    // 合併伺服器任務與本地任務
    serverTasks.forEach(serverTask => {
      const existingTask = tasks.value.find(t => t.task_id === serverTask.task_id)
      if (existingTask) {
        // 保存 cancelling 狀態，避免被伺服器回應覆蓋
        const cancelling = existingTask.cancelling
        Object.assign(existingTask, serverTask)
        if (cancelling !== undefined) {
          existingTask.cancelling = cancelling
        }
      } else {
        tasks.value.push(serverTask)
      }
    })
  } catch (error) {
    console.error('刷新任務列表失敗:', error)
  }
}

// 生命週期
onMounted(() => {
  refreshTasks()
  startPolling()
})

onUnmounted(() => {
  stopPolling()
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

.header {
  text-align: center;
  color: #2d2d2d;
  margin-bottom: 30px;
}

.header h1 {
  font-size: 36px;
  margin-bottom: 10px;
  text-shadow: 0 2px 8px rgba(139, 69, 19, 0.3);
  font-weight: 700;
}

.header p {
  font-size: 16px;
  opacity: 0.8;
}

.stats-panel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}

.stat-item {
  text-align: center;
  padding: 20px;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 12px;
  border: 1px solid rgba(255, 250, 235, 0.6);
  backdrop-filter: blur(15px) saturate(180%);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  transition: all 0.3s;
}

.stat-item:hover {
  border-color: rgba(255, 253, 245, 0.9);
  box-shadow: 0 6px 20px rgba(255, 250, 235, 0.3);
  transform: translateY(-2px);
}

.stat-label {
  display: block;
  font-size: 14px;
  color: rgba(45, 45, 45, 0.6);
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 500;
}

.stat-value {
  display: block;
  font-size: 36px;
  font-weight: bold;
  color: var(--electric-primary);
  text-shadow: 0 2px 4px rgba(139, 69, 19, 0.2);
}

/* 確認對話框 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.3s ease;
}

.modal-content {
  width: 90%;
  max-width: 500px;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-body {
  padding: 28px;
}

.modal-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid rgba(221, 132, 72, 0.15);
}

.modal-section:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}

.section-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 600;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.file-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
}

.file-info:last-child {
  margin-bottom: 0;
}

.file-info .label {
  color: rgba(45, 45, 45, 0.6);
  font-weight: 500;
}

.file-info .value {
  color: rgba(45, 45, 45, 0.95);
  font-weight: 600;
}

.checkbox-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.checkbox-item input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
  accent-color: var(--electric-primary);
  flex-shrink: 0;
}

.checkbox-item label {
  cursor: pointer;
  font-size: 14px;
  color: rgba(45, 45, 45, 0.9);
  font-weight: 500;
}

.sub-setting {
  margin-top: 14px;
  padding-left: 28px;
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.sub-label {
  display: block;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.8);
  font-weight: 500;
  margin-bottom: 8px;
}

.sub-label .hint {
  display: block;
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  font-weight: 400;
  margin-top: 4px;
}

.select-input {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
  cursor: pointer;
}

.select-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.number-input {
  width: 100%;
  padding: 10px 12px;
  font-size: 14px;
  border: 2px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  color: #2d2d2d;
  transition: all 0.3s;
}

.number-input:focus {
  outline: none;
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.number-input::placeholder {
  color: rgba(45, 45, 45, 0.4);
}

.modal-actions {
  display: flex;
  gap: 12px;
  margin-top: 24px;
}

.modal-actions .btn {
  flex: 1;
  padding: 12px 24px;
  font-size: 15px;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
}

.btn-primary {
  background: var(--electric-primary);
  color: white;
  box-shadow: 0 4px 12px rgba(221, 132, 72, 0.3);
}

.btn-primary:hover {
  background: #c97840;
  box-shadow: 0 6px 16px rgba(221, 132, 72, 0.5);
  transform: translateY(-2px);
}

.btn-secondary {
  background: rgba(221, 132, 72, 0.1);
  color: var(--electric-primary);
  border: 2px solid rgba(221, 132, 72, 0.3);
}

.btn-secondary:hover {
  background: rgba(221, 132, 72, 0.2);
  border-color: var(--electric-primary);
  transform: translateY(-2px);
}
</style>
