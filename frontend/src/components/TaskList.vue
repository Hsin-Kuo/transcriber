<template>
  <div class="task-list">


    <!-- 標籤篩選區 -->
    <div v-if="allTags.length > 0" class="filter-section">
      <svg class="filter-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon>
      </svg>

      <div class="filter-tags">
        <div
          v-for="(tag, index) in displayedTags"
          :key="tag"
          class="filter-tag-item"
          :class="{
            'editing': isEditingFilterTags,
            'dragging': draggingIndex === index,
            'drag-over': dragOverIndex === index
          }"
          :draggable="isEditingFilterTags"
          @dragstart="handleDragStart(index, $event)"
          @dragover.prevent="handleDragOver(index, $event)"
          @drop="handleDrop(index, $event)"
          @dragend="handleDragEnd"
        >
          <!-- 編輯模式：拖曳提示圖標 -->
          <div v-if="isEditingFilterTags" class="drag-handle" title="拖曳調整順序">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="8" y1="6" x2="21" y2="6"></line>
              <line x1="8" y1="12" x2="21" y2="12"></line>
              <line x1="8" y1="18" x2="21" y2="18"></line>
              <line x1="3" y1="6" x2="3.01" y2="6"></line>
              <line x1="3" y1="12" x2="3.01" y2="12"></line>
              <line x1="3" y1="18" x2="3.01" y2="18"></line>
            </svg>
          </div>

          <!-- 編輯模式：順序控制（保留作為備選） -->
          <div v-if="false && isEditingFilterTags" class="tag-order-controls">
            <button
              class="btn-move-tag"
              :disabled="index === 0"
              @click="moveTagUp(index)"
              title="上移"
            >
              ▲
            </button>
            <button
              class="btn-move-tag"
              :disabled="index === displayedTags.length - 1"
              @click="moveTagDown(index)"
              title="下移"
            >
              ▼
            </button>
          </div>

          <!-- 編輯模式：可點擊編輯標籤文字 -->
          <input
            v-if="isEditingFilterTags && editingFilterTag === tag"
            type="text"
            class="filter-tag-input"
            v-model="editingFilterTagText"
            @blur="finishEditingFilterTag"
            @keyup.enter="finishEditingFilterTag"
            @keyup.esc="cancelEditingFilterTag"
            ref="filterTagInput"
            :style="{
              borderColor: getTagColor(tag),
              color: getTagColor(tag)
            }"
          />
          <!-- 標籤按鈕 -->
          <button
            v-else
            class="filter-tag-btn"
            :class="{ active: selectedFilterTags.includes(tag) }"
            :style="{
              '--tag-color': getTagColor(tag),
              color: getTagColor(tag)
            }"
            @click="isEditingFilterTags ? startEditingFilterTag(tag) : toggleFilterTag(tag)"
            :title="isEditingFilterTags ? '點擊編輯標籤名稱' : ''"
          >
            {{ tag }}
          </button>

          <!-- 編輯模式：顏色選擇器 -->
          <div v-if="isEditingFilterTags" class="tag-color-picker-wrapper">
            <button
              :ref="el => setColorPickerButtonRef(tag, el)"
              class="btn-color-picker"
              :title="`設定 ${tag} 的顏色`"
              @click="toggleColorPicker(tag)"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"></path>
              </svg>
            </button>
          </div>
        </div>
      </div>

      <div class="filter-header-actions">
        <button
          v-if="!isEditingFilterTags"
          class="btn-edit-filter"
          @click="startEditingFilter"
          title="編輯標籤"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
          </svg>
        </button>
        <template v-else>
          <button
            class="btn-save-filter"
            @click="saveFilterEdit"
            title="儲存"
          >
            ✓
          </button>
        </template>
        <button
          v-if="selectedFilterTags.length > 0 && !isEditingFilterTags"
          class="btn-clear-filter"
          @click="clearFilter"
          title="清除篩選"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
          </svg>
        </button>
      </div>
    </div>
    <div class="list-header">
      <div class="header-actions">
        <button
          class="btn btn-secondary btn-batch-edit"
          :class="{ active: isBatchEditMode }"
          @click="toggleBatchEditMode"
          :title="isBatchEditMode ? '退出批次編輯' : '批次編輯'"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 11l3 3L22 4"></path>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
          </svg>
          {{ isBatchEditMode ? '退出編輯' : '批次編輯' }}
        </button>
        <button class="btn btn-secondary btn-icon" @click="emit('refresh')" title="Refresh">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
          </svg>
        </button>
      </div>
    </div>
    <!-- 批次編輯工具列 -->
    <div v-if="isBatchEditMode" class="batch-toolbar">
      <div class="batch-toolbar-header">
        <div class="batch-header-left">
          <button class="btn-batch-select-all" @click="toggleSelectAll">
            <input
              type="checkbox"
              :checked="selectedTaskIds.size === sortedTasks.length && sortedTasks.length > 0"
              :indeterminate="selectedTaskIds.size > 0 && selectedTaskIds.size < sortedTasks.length"
              readonly
            />
            <span>{{ selectedTaskIds.size === sortedTasks.length && sortedTasks.length > 0 ? '取消全選' : '全選' }}</span>
          </button>
          <span class="batch-selection-count">
            已選擇 {{ selectedTaskIds.size }} / {{ sortedTasks.length }} 個任務
          </span>
        </div>

        <div class="batch-header-right">
          <button
            v-if="selectedTaskIds.size > 0"
            class="btn-batch-action btn-batch-delete"
            @click="batchDelete"
            :title="`刪除選中的 ${selectedTaskIds.size} 個任務`"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
            批次刪除 ({{ selectedTaskIds.size }})
          </button>
        </div>
      </div>

      <div v-if="selectedTaskIds.size > 0" class="batch-actions">

        <!-- 緊湊型標籤管理區域 -->
        <div class="batch-tags-section-compact" :class="{ 'collapsed': isTagSectionCollapsed }">
          <!-- 標籤區域標題和摺疊按鈕 -->
          <div class="batch-tags-header">
            <div class="batch-tags-info">
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path>
                <line x1="7" y1="7" x2="7.01" y2="7"></line>
              </svg>
              <span class="tags-title">標籤批次編輯</span>
              <span class="tags-stats">已加入 {{ selectedTasksTags.commonTags.length }} • 可用 {{ selectedTasksTags.candidateTags.length }}</span>
            </div>
            <button class="btn-collapse" @click="isTagSectionCollapsed = !isTagSectionCollapsed" :title="isTagSectionCollapsed ? '展開' : '收合'">
              {{ isTagSectionCollapsed ? '▼' : '▲' }}
            </button>
          </div>

          <!-- 標籤列表（可摺疊） -->
          <div v-show="!isTagSectionCollapsed" class="batch-tags-content">
            <!-- 統一的標籤列表 -->
            <div v-if="unifiedTagsList.length > 0" class="tags-pills-container">
              <div class="tags-pills-list">
                <button
                  v-for="item in unifiedTagsList"
                  :key="item.tag"
                  class="tag-pill"
                  :class="{ 'tag-added': item.isAdded, 'tag-available': !item.isAdded }"
                  :style="{
                    color: getTagColor(item.tag)
                  }"
                  @click="item.isAdded ? quickBatchRemoveTag(item.tag) : quickBatchAddTag(item.tag)"
                  :title="item.isAdded ? `點擊移除「${item.tag}」` : `點擊加入「${item.tag}」`"
                >
                  <svg class="pill-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <template v-if="item.isAdded">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </template>
                    <template v-else>
                      <line x1="12" y1="5" x2="12" y2="19"></line>
                      <line x1="5" y1="12" x2="19" y2="12"></line>
                    </template>
                  </svg>
                  <span>{{ item.tag }}</span>
                </button>
              </div>
            </div>

            <!-- 無標籤提示 -->
            <div v-else class="batch-tags-empty">
              尚無可用標籤
            </div>

            <!-- 手動輸入 -->
            <div class="batch-manual-input-compact">
              <input
                type="text"
                v-model="batchTagInput"
                placeholder="手動輸入新標籤（逗號分隔）"
                class="manual-input-field"
                @keydown.enter="batchAddTags"
              />
              <button class="btn-manual-add" @click="batchAddTags" :disabled="!batchTagInput.trim()">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 5v14M5 12h14"></path>
                </svg>
                加入
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="tasks.length === 0" class="empty-state">
      <p>尚無轉錄任務</p>
    </div>

    <div v-else class="tasks" :class="{ 'batch-mode': isBatchEditMode }">
      <div
        v-for="task in sortedTasks"
        :key="task.task_id"
        class="electric-card task-wrapper"
      >
        <div class="electric-inner">
          <div class="electric-border-outer">
            <div class="electric-main task-item" :class="{ 'animated': task.status === 'processing', 'batch-edit-mode': isBatchEditMode }">
              <!-- 批次編輯選擇框 -->
              <div v-if="isBatchEditMode" class="batch-select-checkbox">
                <input
                  type="checkbox"
                  :checked="selectedTaskIds.has(task.task_id)"
                  @change="toggleTaskSelection(task.task_id)"
                  class="batch-checkbox"
                />
              </div>

              <div class="task-main">
                <div class="task-info">
                  <div class="task-header">
                    <h3>{{ task.custom_name || task.file?.filename || task.filename || task.file }}</h3>
                    <template v-if="task.status !== 'completed'">
                      <span class="task-divider">/</span>
                      <span :class="['badge', `badge-${task.status}`]">
                        {{ getStatusText(task.status) }}
                      </span>
                    </template>
                  </div>

                  <div class="task-meta">
                    <span v-if="getAudioDuration(task)" class="meta-item">
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M9 18V5l12-2v13"></path>
                        <circle cx="6" cy="18" r="3"></circle>
                        <circle cx="18" cy="16" r="3"></circle>
                      </svg>
                      {{ getAudioDuration(task) }}
                    </span>
                    <span v-if="task.timestamps?.created_at || task.created_at" class="meta-item">
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                      </svg>
                      {{ task.timestamps?.created_at || task.created_at }}
                    </span>
                    <span v-if="task.config?.diarize || task.diarize" class="badge-diarize" :title="(task.config?.max_speakers || task.max_speakers) ? `最多 ${task.config?.max_speakers || task.max_speakers} 位講者` : '自動偵測講者人數'">
                      說話者辨識{{ (task.config?.max_speakers || task.max_speakers) ? ` (≤${task.config?.max_speakers || task.max_speakers}人)` : '' }}
                    </span>
                  </div>

                  <!-- 標籤列 -->
                  <div class="task-tags-section">
                    <!-- 編輯模式 -->
                    <div v-if="editingTaskId === task.task_id" class="tag-edit-mode">
                      <div class="tag-edit-header">
                        <span class="tag-edit-label">編輯標籤</span>
                        <div class="tag-edit-actions">
                          <button class="btn-tag-action btn-save" @click="saveTaskTags(task)" title="儲存">
                            ✓
                          </button>
                          <button class="btn-tag-action btn-cancel" @click="cancelTagEdit" title="取消">
                            ✕
                          </button>
                        </div>
                      </div>
                      <div class="tag-input-wrapper-inline">
                        <input
                          type="text"
                          v-model="editingTagInput"
                          @keydown.enter.prevent="addEditingTag"
                          @keydown.comma.prevent="addEditingTag"
                          placeholder="輸入標籤後按 Enter"
                          class="tag-input-inline"
                        />
                        <button
                          type="button"
                          class="btn-add-tag-inline"
                          @click="addEditingTag"
                          :disabled="!editingTagInput.trim()"
                        >
                          +
                        </button>
                      </div>

                      <!-- 可快速選擇的現有標籤 -->
                      <div v-if="availableTags.length > 0" class="available-tags-section">
                        <div class="available-tags-label">快速選擇：</div>
                        <div class="available-tags">
                          <button
                            v-for="tag in availableTags"
                            :key="tag"
                            type="button"
                            class="available-tag-btn"
                            :style="{
                              backgroundColor: `${getTagColor(tag)}15`,
                              borderColor: getTagColor(tag),
                              color: getTagColor(tag)
                            }"
                            @click="quickAddTag(tag)"
                            :title="`點擊加入 ${tag}`"
                          >
                            + {{ tag }}
                          </button>
                        </div>
                      </div>

                      <div v-if="editingTags.length > 0" class="task-tags">
                        <template v-for="(tag, index) in editingTags" :key="index">
                          <!-- 編輯狀態：顯示輸入框 -->
                          <span
                            v-if="editingTagIndex === index"
                            class="tag-badge-editing"
                            :style="{ backgroundColor: getTagColor(tag) }"
                          >
                            <input
                              type="text"
                              class="tag-text-input"
                              v-model="editingTagText"
                              @keyup.enter="saveEditingTagText(index)"
                              @keyup.esc="cancelEditingTagText"
                              @blur="saveEditingTagText(index)"
                              ref="tagTextInput"
                            />
                            <button
                              type="button"
                              class="save-tag-text"
                              @click="saveEditingTagText(index)"
                              title="儲存"
                            >
                              ✓
                            </button>
                            <button
                              type="button"
                              class="cancel-tag-text"
                              @click="cancelEditingTagText"
                              title="取消"
                            >
                              ✕
                            </button>
                          </span>
                          <!-- 一般狀態：顯示標籤 -->
                          <span
                            v-else
                            class="tag-badge editable"
                            :style="{ backgroundColor: getTagColor(tag) }"
                            @click="startEditingTagText(index, tag)"
                            :title="'點擊編輯標籤'"
                          >
                            {{ tag }}
                            <button
                              type="button"
                              class="remove-tag-inline"
                              @click.stop="removeEditingTag(index)"
                              title="移除"
                            >
                              ×
                            </button>
                          </span>
                        </template>
                      </div>
                    </div>

                    <!-- 顯示模式 -->
                    <div v-else class="task-tags-display">
                      <div v-if="task.tags && task.tags.length > 0" class="task-tags">
                        <span
                          v-for="tag in task.tags"
                          :key="tag"
                          class="tag-badge"
                          :style="{ backgroundColor: getTagColor(tag) }"
                        >
                          {{ tag }}
                        </span>
                        <button
                          class="btn-edit-tags"
                          @click="startEditingTags(task)"
                          title="編輯標籤"
                        >
                          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                          </svg>
                        </button>
                      </div>
                      <button
                        v-else
                        class="btn-add-tags"
                        @click="startEditingTags(task)"
                        title="新增標籤"
                      >
                        + 新增標籤
                      </button>
                    </div>
                  </div>

                  <div v-if="task.progress && isTaskExpanded(task.task_id)" class="task-progress">
                    <div class="progress-bar">
                      <div
                        class="progress-fill"
                        :style="{ width: getProgressWidth(task) }"
                      ></div>
                    </div>
                    <p class="progress-text">
                      <span v-if="['pending', 'processing'].includes(task.status)" class="spinner"></span>
                      {{ task.progress }}
                      <span v-if="task.progress_percentage !== undefined && task.progress_percentage !== null" class="progress-percentage">
                        {{ Math.round(task.progress_percentage) }}%
                      </span>
                      <span v-if="task.estimated_completion_text && ['pending', 'processing'].includes(task.status)" class="estimate-time">
                        · 預計完成時間：{{ task.estimated_completion_text }}
                      </span>
                    </p>
                    <!-- 顯示說話者辨識狀態 -->
                    <p v-if="(task.config?.diarize || task.diarize) && getDiarizationStatusText(task)" class="diarization-status" :class="`status-${task.stats?.diarization?.status || task.diarization_status}`">
                      {{ getDiarizationStatusText(task) }}
                    </p>
                    <!-- 顯示正在處理的 chunks -->
                    <p v-if="getProcessingChunksText(task)" class="processing-chunks">
                      {{ getProcessingChunksText(task) }}
                    </p>
                  </div>

                  <div v-if="task.status === 'completed' && (task.result?.text_length || task.text_length) && isTaskExpanded(task.task_id)" class="task-result">
                    <div>📝 已轉錄 {{ task.result?.text_length || task.text_length }} 字</div>
                    <div v-if="task.duration_text" class="duration">
                      ⏱️ 處理時間：{{ task.duration_text }}
                    </div>
                  </div>

                  <div v-if="task.status === 'failed' && task.error" class="task-error">
                    ❌ {{ task.error }}
                  </div>
                </div>

                <div class="task-actions">
                  <!-- 保留音檔開關（僅已完成且有音檔的任務） -->
                  <div v-if="task.status === 'completed' && (task.result?.audio_file || task.audio_file)" class="keep-audio-toggle" :title="getKeepAudioTooltip(task)">
                    <label class="toggle-label">
                      <div class="toggle-switch-wrapper">
                        <input
                          type="checkbox"
                          :checked="task.keep_audio"
                          @change="toggleKeepAudio(task)"
                          :disabled="!task.keep_audio && keepAudioCount >= 3"
                          class="toggle-input"
                        />
                        <span class="toggle-slider">
                          <!-- 解鎖圖標（未選中時顯示） -->
                          <svg class="lock-icon unlock-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                            <path d="M7 11V7a5 5 0 0 1 9.9-1"></path>
                          </svg>
                          <!-- 上鎖圖標（選中時顯示） -->
                          <svg class="lock-icon locked-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                          </svg>
                        </span>
                      </div>
                      <span v-if="isNewestTask(task)" class="newest-badge" title="最新任務的音檔會自動保留">new</span>
                    </label>
                  </div>

                  <!-- 已完成任務的三聯按鈕組 -->
                  <div v-if="task.status === 'completed'" class="btn-group">
                    <button
                      class="btn btn-view btn-group-left btn-icon"
                      @click="emit('view', task.task_id)"
                      title="瀏覽逐字稿"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                        <circle cx="12" cy="12" r="3"></circle>
                      </svg>
                    </button>
                    <button
                      class="btn btn-download btn-group-middle btn-icon"
                      @click="emit('download', task.task_id)"
                      title="下載逐字稿"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                      </svg>
                    </button>
                    <button
                      class="btn btn-danger btn-group-right btn-icon"
                      @click="emit('delete', task.task_id)"
                      title="刪除任務及檔案"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        <line x1="10" y1="11" x2="10" y2="17"></line>
                        <line x1="14" y1="11" x2="14" y2="17"></line>
                      </svg>
                    </button>
                  </div>

                  <!-- 進行中任務的按鈕 -->
                  <button
                    v-if="['pending', 'processing'].includes(task.status)"
                    class="btn btn-warning"
                    @click="emit('cancel', task.task_id)"
                    :disabled="task.cancelling"
                    title="取消正在執行的任務"
                  >
                    <span v-if="task.cancelling" class="spinner"></span>
                    {{ task.cancelling ? '取消中...' : '取消' }}
                  </button>

                  <!-- 失敗或取消任務的刪除按鈕 -->
                  <button
                    v-if="['failed', 'cancelled'].includes(task.status)"
                    class="btn btn-danger"
                    @click="emit('delete', task.task_id)"
                    title="刪除任務及檔案"
                  >
                    刪除
                  </button>
                </div>
              </div>
            </div>
          </div>
          <!-- 光暈層 -->
          <div class="electric-glow-1"></div>
          <div class="electric-glow-2"></div>
        </div>
        <!-- 疊加效果 -->
        <div class="electric-overlay"></div>
        <div class="electric-bg-glow"></div>
      </div>
    </div>

    <!-- 顏色選擇器背景遮罩 -->
    <div
      v-if="colorPickerTag"
      class="color-picker-overlay"
      @click="closeColorPicker"
    ></div>

    <!-- 顏色選擇器彈窗（固定定位，顯示在最上層） -->
    <div
      v-if="colorPickerTag"
      class="color-picker-popup"
      :style="colorPickerPosition"
      @click.stop
    >
      <div class="color-picker-header">
        <span>選擇顏色</span>
        <button class="btn-close-picker" @click="closeColorPicker">✕</button>
      </div>
      <input
        type="color"
        :value="getTagColor(colorPickerTag)"
        @input="updateTagColor(colorPickerTag, $event.target.value)"
        class="color-input"
      />
      <div class="preset-colors">
        <button
          v-for="color in presetColors"
          :key="color"
          class="preset-color-btn"
          :style="{ backgroundColor: color }"
          @click="updateTagColor(colorPickerTag, color)"
          :title="color"
        ></button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch, nextTick } from 'vue'
import api from '../utils/api'

const props = defineProps({
  tasks: {
    type: Array,
    required: true
  }
})

const emit = defineEmits(['download', 'refresh', 'delete', 'cancel', 'view'])

const tagColors = ref({})
const tagsData = ref([]) // 存儲完整的標籤信息（包含 ID）
const editingTaskId = ref(null)
const editingTags = ref([])
const editingTagInput = ref('')
const editingTagIndex = ref(null)
const editingTagText = ref('')
const tagTextInput = ref(null)
const selectedFilterTags = ref([])
const colorPickerTag = ref(null)
const colorPickerPosition = ref({})
const colorPickerButtons = ref({})
const isEditingFilterTags = ref(false)
const editingTagOrder = ref([])
const draggingIndex = ref(null)
const dragOverIndex = ref(null)
const customTagOrder = ref([])
const editingFilterTag = ref(null) // 正在編輯的篩選標籤名稱
const editingFilterTagText = ref('') // 編輯中的標籤文字
const isRenamingTag = ref(false) // 是否正在重命名標籤（防止併發操作）

// ==== 批次編輯模式 ====
const isBatchEditMode = ref(false)
const selectedTaskIds = ref(new Set())
const batchTagInput = ref('')
const isTagSectionCollapsed = ref(true)

// 預設顏色選項
const presetColors = [
  '#667eea', '#f093fb', '#4facfe', '#43e97b', '#fa709a',
  '#feca57', '#48dbfb', '#ff6b6b', '#ee5a6f', '#c44569',
  '#a29bfe', '#fd79a8', '#fdcb6e', '#00b894', '#0984e3',
  '#6c5ce7', '#e17055', '#74b9ff', '#55efc4', '#ffeaa7'
]

// 獲取所有唯一的標籤
const allTags = computed(() => {
  const tags = new Set()
  props.tasks.forEach(task => {
    if (task.tags && task.tags.length > 0) {
      task.tags.forEach(tag => tags.add(tag))
    }
  })

  const tagArray = Array.from(tags)

  // 如果有自定義順序，使用自定義順序
  if (customTagOrder.value.length > 0) {
    // 先按自定義順序排列已有的標籤
    const orderedTags = customTagOrder.value.filter(tag => tagArray.includes(tag))
    // 添加新標籤（不在自定義順序中的）
    const newTags = tagArray.filter(tag => !customTagOrder.value.includes(tag)).sort()
    return [...orderedTags, ...newTags]
  }

  return tagArray.sort()
})

// 顯示的標籤（編輯模式使用自定義順序）
const displayedTags = computed(() => {
  if (isEditingFilterTags.value && editingTagOrder.value.length > 0) {
    return editingTagOrder.value
  }
  return allTags.value
})

const sortedTasks = computed(() => {
  let filtered = [...props.tasks]

  // 標籤篩選（OR 邏輯：任務只要有其中一個被選中的標籤就顯示）
  if (selectedFilterTags.value.length > 0) {
    filtered = filtered.filter(task => {
      if (!task.tags || task.tags.length === 0) return false
      return task.tags.some(tag => selectedFilterTags.value.includes(tag))
    })
  }

  // 依狀態排序
  return filtered.sort((a, b) => {
    const statusOrder = { processing: 0, pending: 1, completed: 2, failed: 3 }
    return statusOrder[a.status] - statusOrder[b.status]
  })
})

// 檢查任務是否展開 - 只有進行中的任務才展開
function isTaskExpanded(taskId) {
  const task = sortedTasks.value.find(t => t.task_id === taskId)
  if (!task) return false
  // 只有 pending 和 processing 狀態的任務才展開
  return ['pending', 'processing'].includes(task.status)
}

function getStatusText(status) {
  const statusMap = {
    pending: '等待中',
    processing: '處理中',
    completed: '已完成',
    failed: '失敗',
    cancelled: '已取消'
  }
  return statusMap[status] || status
}

function getAudioDuration(task) {
  // 優先使用新的 audio_duration_seconds 欄位（音檔實際時長）
  const duration = task.stats?.audio_duration_seconds || task.audio_duration_seconds
  if (!duration) {
    return null
  }

  const minutes = Math.floor(duration / 60)
  const seconds = Math.floor(duration % 60)

  if (minutes > 0) {
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  } else {
    return `0:${seconds.toString().padStart(2, '0')}`
  }
}

function getProgressWidth(task) {
  if (task.status === 'completed') return '100%'
  if (task.status === 'failed') return '100%'

  // 優先使用基於時間權重的進度百分比
  if (task.progress_percentage !== undefined && task.progress_percentage !== null) {
    const percentage = Math.min(Math.max(task.progress_percentage, 2), 99)
    return `${percentage}%`
  }

  // 後備：如果有 chunk 資訊，根據完成數量計算簡單進度
  if (task.status === 'processing' && task.total_chunks && task.completed_chunks !== undefined) {
    const percentage = (task.completed_chunks / task.total_chunks) * 100
    return `${Math.min(Math.max(percentage, 5), 95)}%`
  }

  // 預設進度
  if (task.status === 'processing') return '30%'
  return '10%'
}

function getDiarizationStatusText(task) {
  // 支援巢狀結構和扁平結構
  const diarizationStatus = task.stats?.diarization?.status || task.diarization_status
  if (!diarizationStatus) {
    return null
  }

  const status = diarizationStatus
  const numSpeakers = task.stats?.diarization?.num_speakers || task.diarization_num_speakers
  const duration = task.stats?.diarization?.duration_seconds || task.diarization_duration_seconds

  if (status === 'running') {
    return '說話者辨識進行中...'
  } else if (status === 'completed') {
    const parts = ['說話者辨識完成']
    if (numSpeakers) {
      parts.push(`識別到 ${numSpeakers} 位說話者`)
    }
    if (duration) {
      const minutes = Math.floor(duration / 60)
      const seconds = Math.floor(duration % 60)
      if (minutes > 0) {
        parts.push(`耗時 ${minutes}分${seconds}秒`)
      } else {
        parts.push(`耗時 ${seconds}秒`)
      }
    }
    return parts.join(' · ')
  } else if (status === 'failed') {
    return '說話者辨識失敗'
  }

  return null
}

function getProcessingChunksText(task) {
  if (!task.chunks || task.chunks.length === 0 || task.status !== 'processing') {
    return null
  }

  const processingChunks = task.chunks.filter(c => c.status === 'processing').map(c => c.chunk_id)
  const completedChunks = task.chunks.filter(c => c.status === 'completed').map(c => c.chunk_id)

  if (processingChunks.length === 0) {
    return null
  }

  const parts = []

  if (completedChunks.length > 0) {
    parts.push(`✓ 已完成：Chunk ${completedChunks.join(', ')}`)
  }

  if (processingChunks.length > 0) {
    parts.push(`⏳ 處理中：Chunk ${processingChunks.join(', ')}`)
  }

  return parts.join(' · ')
}

// 標籤相關功能
async function fetchTagColors() {
  try {
    const response = await api.get('/tags')
    const colors = {}
    const tags = response.data || []

    // 存儲完整的標籤信息
    tagsData.value = tags

    tags.forEach(tag => {
      if (tag.color) {
        colors[tag.name] = tag.color
      }
    })
    tagColors.value = colors
  } catch (error) {
    console.error('獲取標籤顏色失敗:', error)
  }
}

async function fetchTagOrder() {
  try {
    const response = await api.get('/tags/order')
    if (response.data.order && response.data.order.length > 0) {
      customTagOrder.value = response.data.order
      console.log('✅ 已從伺服器載入標籤順序：', response.data.count, '個標籤')
    }
  } catch (error) {
    console.error('獲取標籤順序失敗:', error)
  }
}

function getTagColor(tagName) {
  // 如果有設定顏色，使用設定的顏色
  if (tagColors.value[tagName]) {
    return tagColors.value[tagName]
  }

  // 否則根據標籤名稱生成一致的預設顏色
  const colors = [
    '#667eea', // 紫藍
    '#f093fb', // 粉紫
    '#4facfe', // 天藍
    '#43e97b', // 青綠
    '#fa709a', // 粉紅
    '#feca57', // 橘黃
    '#48dbfb', // 青藍
    '#ff6b6b', // 珊瑚紅
    '#ee5a6f', // 玫瑰紅
    '#c44569', // 暗紅
  ]

  // 使用標籤名稱的 hash 來選擇顏色
  let hash = 0
  for (let i = 0; i < tagName.length; i++) {
    hash = tagName.charCodeAt(i) + ((hash << 5) - hash)
  }
  const index = Math.abs(hash) % colors.length
  return colors[index]
}

// 標籤編輯功能
function startEditingTags(task) {
  editingTaskId.value = task.task_id
  editingTags.value = task.tags ? [...task.tags] : []
  editingTagInput.value = ''
}

function addEditingTag() {
  const tag = editingTagInput.value.trim()
  if (tag && !editingTags.value.includes(tag)) {
    editingTags.value.push(tag)
    editingTagInput.value = ''
  } else if (editingTags.value.includes(tag)) {
    editingTagInput.value = ''
  }
}

function quickAddTag(tag) {
  if (!editingTags.value.includes(tag)) {
    editingTags.value.push(tag)
  }
}

function removeEditingTag(index) {
  editingTags.value.splice(index, 1)
}

// 計算可用的標籤（所有標籤中排除已選的）
const availableTags = computed(() => {
  if (editingTaskId.value === null) {
    return []
  }
  return allTags.value.filter(tag => !editingTags.value.includes(tag))
})

async function saveTaskTags(task) {
  try {
    await api.put(`/tasks/${task.task_id}/tags`, {
      tags: editingTags.value
    })

    // 更新任務的標籤
    task.tags = [...editingTags.value]

    // 重新獲取標籤顏色（如果有新標籤）
    await fetchTagColors()

    // 清除編輯狀態
    editingTaskId.value = null
    editingTags.value = []
    editingTagInput.value = ''
  } catch (error) {
    console.error('更新標籤失敗:', error)
    alert('更新標籤失敗：' + (error.response?.data?.detail || error.message))
  }
}

function cancelTagEdit() {
  editingTaskId.value = null
  editingTags.value = []
  editingTagInput.value = ''
  editingTagIndex.value = null
  editingTagText.value = ''
}

// 標籤文字編輯功能
async function startEditingTagText(index, tag) {
  editingTagIndex.value = index
  editingTagText.value = tag

  // 等待 DOM 更新後自動聚焦輸入框
  await nextTick()
  if (tagTextInput.value) {
    // tagTextInput.value 可能是陣列（因為在 v-for 中）
    const input = Array.isArray(tagTextInput.value) ? tagTextInput.value[0] : tagTextInput.value
    if (input) {
      input.focus()
      input.select()
    }
  }
}

function saveEditingTagText(index) {
  const newText = editingTagText.value.trim()
  if (newText && newText !== editingTags.value[index]) {
    // 檢查新標籤是否已存在
    if (!editingTags.value.includes(newText)) {
      editingTags.value[index] = newText
    }
  }
  editingTagIndex.value = null
  editingTagText.value = ''
}

function cancelEditingTagText() {
  editingTagIndex.value = null
  editingTagText.value = ''
}

// 標籤篩選功能
function toggleFilterTag(tag) {
  const index = selectedFilterTags.value.indexOf(tag)
  if (index > -1) {
    selectedFilterTags.value.splice(index, 1)
  } else {
    selectedFilterTags.value.push(tag)
  }
}

function clearFilter() {
  selectedFilterTags.value = []
}

// 篩選標籤文字編輯功能
function startEditingFilterTag(tag) {
  // 如果正在重命名其他標籤，阻止操作
  if (isRenamingTag.value) {
    return
  }
  editingFilterTag.value = tag
  editingFilterTagText.value = tag
  // 在下一個 tick 後聚焦輸入框
  nextTick(() => {
    const inputs = document.querySelectorAll('.filter-tag-input')
    inputs.forEach(input => input.focus())
  })
}

async function finishEditingFilterTag() {
  // 如果已經在重命名，防止重複執行
  if (isRenamingTag.value) {
    return
  }

  const oldTag = editingFilterTag.value
  const newTag = editingFilterTagText.value.trim()

  // 如果標籤沒有改變或新標籤為空，取消編輯
  if (!newTag || newTag === oldTag) {
    cancelEditingFilterTag()
    return
  }

  // 檢查新標籤名稱是否已存在（排除當前正在編輯的標籤）
  // 在編輯模式下，應該檢查 editingTagOrder，因為那是用戶當前看到的標籤列表
  const currentTags = isEditingFilterTags.value && editingTagOrder.value.length > 0
    ? editingTagOrder.value
    : allTags.value
  const otherTags = currentTags.filter(tag => tag !== oldTag)
  if (otherTags.includes(newTag)) {
    alert(`標籤 "${newTag}" 已存在，請使用其他名稱`)
    return
  }

  // 設置重命名鎖，防止併發操作
  isRenamingTag.value = true

  try {
    // 更新所有任務中的標籤
    const tasksToUpdate = props.tasks.filter(task =>
      task.tags && task.tags.includes(oldTag)
    )

    // 批量更新所有任務（使用 Promise.all 並行處理）
    await Promise.all(
      tasksToUpdate.map(task => {
        const updatedTags = task.tags.map(t => t === oldTag ? newTag : t)
        return api.put(`/tasks/${task.task_id}/tags`, {
          tags: updatedTags
        })
      })
    )

    // 更新自定義標籤順序
    if (customTagOrder.value.includes(oldTag)) {
      const index = customTagOrder.value.indexOf(oldTag)
      customTagOrder.value[index] = newTag
    }

    // 更新編輯中的標籤順序
    if (editingTagOrder.value.includes(oldTag)) {
      const index = editingTagOrder.value.indexOf(oldTag)
      editingTagOrder.value[index] = newTag
    }

    // 更新標籤顏色
    if (tagColors.value[oldTag]) {
      tagColors.value[newTag] = tagColors.value[oldTag]
      delete tagColors.value[oldTag]
      // 保存新標籤的顏色
      await updateTagColor(newTag, tagColors.value[newTag])
    }

    // 更新選中的篩選標籤
    if (selectedFilterTags.value.includes(oldTag)) {
      const index = selectedFilterTags.value.indexOf(oldTag)
      selectedFilterTags.value[index] = newTag
    }

    console.log(`✅ 標籤 "${oldTag}" 已重命名為 "${newTag}"`)

    // 刷新任務列表以確保前後端數據同步
    emit('refresh')
  } catch (error) {
    console.error('重命名標籤失敗:', error)
    alert('重命名標籤失敗：' + (error.response?.data?.detail || error.message))
  } finally {
    // 釋放重命名鎖
    isRenamingTag.value = false
  }

  // 清除編輯狀態
  cancelEditingFilterTag()
}

function cancelEditingFilterTag() {
  editingFilterTag.value = null
  editingFilterTagText.value = ''
  // 確保釋放鎖
  isRenamingTag.value = false
}

// 標籤編輯模式
function startEditingFilter() {
  isEditingFilterTags.value = true
  editingTagOrder.value = [...allTags.value]
}

async function saveFilterEdit() {
  // 保存標籤順序到伺服器
  customTagOrder.value = [...editingTagOrder.value]
  try {
    // 將標籤名稱轉換為標籤 ID
    const tagIds = editingTagOrder.value.map(tagName => {
      const tagObj = tagsData.value.find(t => t.name === tagName)
      const tagId = tagObj ? (tagObj._id || tagObj.tag_id) : null
      console.log(`標籤 "${tagName}" -> ID: ${tagId}`, tagObj)
      return tagId
    }).filter(id => id !== null)

    console.log('發送的標籤 ID 列表:', tagIds)
    console.log('tagsData:', tagsData.value)

    await api.put('/tags/order', {
      tag_ids: tagIds
    })
    console.log('✅ 已儲存標籤順序到伺服器')
  } catch (error) {
    console.error('保存標籤順序失敗:', error)
    alert('保存標籤順序失敗：' + (error.response?.data?.detail || error.message))
  }

  isEditingFilterTags.value = false
  closeColorPicker()
}

function cancelFilterEdit() {
  isEditingFilterTags.value = false
  editingTagOrder.value = []
  closeColorPicker()
}

function moveTagUp(index) {
  if (index > 0) {
    const temp = editingTagOrder.value[index]
    editingTagOrder.value[index] = editingTagOrder.value[index - 1]
    editingTagOrder.value[index - 1] = temp
  }
}

function moveTagDown(index) {
  if (index < editingTagOrder.value.length - 1) {
    const temp = editingTagOrder.value[index]
    editingTagOrder.value[index] = editingTagOrder.value[index + 1]
    editingTagOrder.value[index + 1] = temp
  }
}

// 拖放排序功能
function handleDragStart(index, event) {
  draggingIndex.value = index
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', index.toString())
}

function handleDragOver(index, event) {
  if (draggingIndex.value === null || draggingIndex.value === index) {
    return
  }
  dragOverIndex.value = index
}

function handleDrop(index) {
  if (draggingIndex.value === null || draggingIndex.value === index) {
    return
  }

  // 重新排序
  const newOrder = [...editingTagOrder.value]
  const draggedItem = newOrder[draggingIndex.value]

  // 移除拖動的項目
  newOrder.splice(draggingIndex.value, 1)

  // 插入到新位置
  newOrder.splice(index, 0, draggedItem)

  editingTagOrder.value = newOrder

  // 重置狀態
  dragOverIndex.value = null
}

function handleDragEnd() {
  draggingIndex.value = null
  dragOverIndex.value = null
}

// 標籤顏色自訂功能
function setColorPickerButtonRef(tag, el) {
  if (el) {
    colorPickerButtons.value[tag] = el
  }
}

function toggleColorPicker(tag) {
  if (colorPickerTag.value === tag) {
    colorPickerTag.value = null
    colorPickerPosition.value = {}
  } else {
    colorPickerTag.value = tag

    // 計算彈窗位置
    const button = colorPickerButtons.value[tag]
    if (button) {
      const rect = button.getBoundingClientRect()
      const popupWidth = 220
      const popupHeight = 240

      // 預設在按鈕下方
      let top = rect.bottom + 8
      let left = rect.left

      // 如果右側空間不足，向左對齊
      if (left + popupWidth > window.innerWidth) {
        left = window.innerWidth - popupWidth - 16
      }

      // 如果下方空間不足，顯示在上方
      if (top + popupHeight > window.innerHeight) {
        top = rect.top - popupHeight - 8
      }

      colorPickerPosition.value = {
        position: 'fixed',
        top: `${top}px`,
        left: `${left}px`
      }
    }
  }
}

function closeColorPicker() {
  colorPickerTag.value = null
  colorPickerPosition.value = {}
}

async function updateTagColor(tagName, color) {
  try {
    // 從 tagsData 中找到對應的標籤對象
    const tagObj = tagsData.value.find(t => t.name === tagName)
    if (!tagObj) {
      throw new Error('找不到標籤信息')
    }

    // 使用正確的 API 端點和標籤 ID
    await api.put(`/tags/${tagObj._id || tagObj.tag_id}`, {
      name: tagObj.name,
      color: color,
      description: tagObj.description || null
    })

    // 更新本地顏色
    tagColors.value[tagName] = color

    // 不自動關閉顏色選擇器，讓使用者可以連續調整多個標籤
  } catch (error) {
    console.error('更新標籤顏色失敗:', error)
    alert('更新標籤顏色失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 監聽 tasks 變化，只在標籤真的改變時重新獲取標籤顏色
watch(() => props.tasks, (newTasks, oldTasks) => {
  // 只有在標籤數量或內容改變時才重新獲取
  const newTagsSet = new Set()
  const oldTagsSet = new Set()

  newTasks.forEach(task => {
    if (task.tags) {
      task.tags.forEach(tag => newTagsSet.add(tag))
    }
  })

  if (oldTasks) {
    oldTasks.forEach(task => {
      if (task.tags) {
        task.tags.forEach(tag => oldTagsSet.add(tag))
      }
    })
  }

  // 只有標籤集合改變時才重新獲取
  if (newTagsSet.size !== oldTagsSet.size ||
      ![...newTagsSet].every(tag => oldTagsSet.has(tag))) {
    fetchTagColors()
  }
}, { deep: true })

// ==== 保留音檔功能 ====
// 計算當前已勾選保留音檔的數量
const keepAudioCount = computed(() => {
  return props.tasks.filter(t =>
    t.status === 'completed' &&
    t.audio_file &&
    t.keep_audio
  ).length
})

// ==== 批次標籤分析 ====
// 分析選中任務的標籤
const selectedTasksTags = computed(() => {
  if (selectedTaskIds.value.size === 0) {
    return {
      commonTags: [],      // 所有選中任務都有的標籤
      candidateTags: []    // 候選標籤（部分任務有的 + 系統中其他標籤）
    }
  }

  // 獲取所有選中的任務
  const selectedTasks = sortedTasks.value.filter(t => selectedTaskIds.value.has(t.task_id))

  if (selectedTasks.length === 0) {
    return { commonTags: [], candidateTags: [] }
  }

  // 收集所有選中任務的標籤
  const allTagsMap = new Map() // tag -> count

  selectedTasks.forEach(task => {
    const tags = task.tags || []
    tags.forEach(tag => {
      allTagsMap.set(tag, (allTagsMap.get(tag) || 0) + 1)
    })
  })

  // 所有任務都有的標籤
  const commonTags = Array.from(allTagsMap.entries())
    .filter(([tag, count]) => count === selectedTasks.length)
    .map(([tag]) => tag)

  // 候選標籤 = 部分任務有的標籤 + 系統中的其他標籤（但不包括 commonTags）
  const candidateTags = Array.from(new Set([
    // 部分任務有的標籤
    ...Array.from(allTagsMap.entries())
      .filter(([tag, count]) => count < selectedTasks.length)
      .map(([tag]) => tag),
    // 系統中的其他標籤
    ...allTags.value.filter(tag => !commonTags.includes(tag))
  ]))

  return { commonTags, candidateTags }
})

// 統一的標籤列表（用於緊湊型顯示）
const unifiedTagsList = computed(() => {
  const { commonTags, candidateTags } = selectedTasksTags.value

  // 合併標籤並標記狀態
  const tagsList = [
    ...commonTags.map(tag => ({ tag, isAdded: true })),
    ...candidateTags.map(tag => ({ tag, isAdded: false }))
  ]

  // 排序：已加入的在前，然後按標籤名稱排序
  return tagsList.sort((a, b) => {
    if (a.isAdded !== b.isAdded) {
      return a.isAdded ? -1 : 1
    }
    return a.tag.localeCompare(b.tag)
  })
})

// 判斷是否為最新的已完成任務
function isNewestTask(task) {
  const completedTasks = props.tasks.filter(t =>
    t.status === 'completed' &&
    t.audio_file
  )

  if (completedTasks.length === 0) return false

  // 按完成時間排序，取最新的
  const sorted = [...completedTasks].sort((a, b) =>
    (b.completed_at || '').localeCompare(a.completed_at || '')
  )

  return sorted[0]?.task_id === task.task_id
}

// 獲取保留音檔勾選框的提示文字
function getKeepAudioTooltip(task) {
  if (isNewestTask(task)) {
    return '最新音檔會自動保留（不計入3個勾選限制）'
  }
  if (!task.keep_audio && keepAudioCount.value >= 3) {
    return '最多只能勾選3個音檔'
  }
  return '勾選以保留此音檔（最多3個）'
}

// 切換保留音檔狀態
async function toggleKeepAudio(task) {
  const oldValue = task.keep_audio
  const newValue = !oldValue

  // 如果要勾選，檢查是否超過限制
  if (newValue && keepAudioCount.value >= 3) {
    alert('最多只能勾選 3 個音檔保留')
    return
  }

  // 先樂觀更新 UI（立即反映變化）
  task.keep_audio = newValue

  try {
    await api.put(`/tasks/${task.task_id}/keep-audio`, {
      keep_audio: newValue
    })

    // 刷新任務列表
    emit('refresh')

  } catch (error) {
    console.error('更新音檔保留狀態失敗:', error)

    // 恢復舊狀態
    task.keep_audio = oldValue

    // 顯示錯誤訊息
    const errorMessage = error.response?.data?.detail || error.message
    alert('更新失敗：' + errorMessage)
  }
}

// ==== 批次編輯功能 ====
// 進入/退出批次編輯模式
function toggleBatchEditMode() {
  isBatchEditMode.value = !isBatchEditMode.value

  // 退出批次編輯模式時，清空選擇
  if (!isBatchEditMode.value) {
    selectedTaskIds.value.clear()
    batchTagInput.value = ''
  }
}

// 切換任務選擇狀態
function toggleTaskSelection(taskId) {
  if (selectedTaskIds.value.has(taskId)) {
    selectedTaskIds.value.delete(taskId)
  } else {
    selectedTaskIds.value.add(taskId)
  }
  // 觸發響應式更新
  selectedTaskIds.value = new Set(selectedTaskIds.value)
}

// 全選/取消全選
function toggleSelectAll() {
  if (selectedTaskIds.value.size === sortedTasks.value.length) {
    // 如果已全選，則取消全選
    selectedTaskIds.value.clear()
  } else {
    // 否則全選
    selectedTaskIds.value = new Set(sortedTasks.value.map(t => t.task_id))
  }
  // 觸發響應式更新
  selectedTaskIds.value = new Set(selectedTaskIds.value)
}

// 批次刪除
async function batchDelete() {
  if (selectedTaskIds.value.size === 0) {
    alert('請先選擇要刪除的任務')
    return
  }

  if (!confirm(`確定要刪除 ${selectedTaskIds.value.size} 個任務嗎？`)) {
    return
  }

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/delete', {
      task_ids: taskIds
    })

    alert(`成功刪除 ${taskIds.length} 個任務`)
    selectedTaskIds.value.clear()
    emit('refresh')
  } catch (error) {
    console.error('批次刪除失敗:', error)
    alert('批次刪除失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 批次加入標籤
async function batchAddTags() {
  if (selectedTaskIds.value.size === 0) {
    alert('請先選擇要加入標籤的任務')
    return
  }

  if (!batchTagInput.value.trim()) {
    alert('請輸入要加入的標籤')
    return
  }

  const tags = batchTagInput.value.split(',').map(t => t.trim()).filter(t => t)

  if (tags.length === 0) {
    alert('請輸入有效的標籤')
    return
  }

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/tags/add', {
      task_ids: taskIds,
      tags: tags
    })

    alert(`成功為 ${taskIds.length} 個任務加入標籤`)
    batchTagInput.value = ''
    emit('refresh')
  } catch (error) {
    console.error('批次加入標籤失敗:', error)
    alert('批次加入標籤失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 批次移除標籤
async function batchRemoveTags() {
  if (selectedTaskIds.value.size === 0) {
    alert('請先選擇要移除標籤的任務')
    return
  }

  if (!batchTagInput.value.trim()) {
    alert('請輸入要移除的標籤')
    return
  }

  const tags = batchTagInput.value.split(',').map(t => t.trim()).filter(t => t)

  if (tags.length === 0) {
    alert('請輸入有效的標籤')
    return
  }

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/tags/remove', {
      task_ids: taskIds,
      tags: tags
    })

    alert(`成功從 ${taskIds.length} 個任務移除標籤`)
    batchTagInput.value = ''
    emit('refresh')
  } catch (error) {
    console.error('批次移除標籤失敗:', error)
    alert('批次移除標籤失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 快速加入標籤（點擊候選標籤）
async function quickBatchAddTag(tag) {
  if (selectedTaskIds.value.size === 0) {
    return
  }

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/tags/add', {
      task_ids: taskIds,
      tags: [tag]
    })

    emit('refresh')
  } catch (error) {
    console.error('批次加入標籤失敗:', error)
    alert('批次加入標籤失敗：' + (error.response?.data?.detail || error.message))
  }
}

// 快速移除標籤（點擊已加入標籤）
async function quickBatchRemoveTag(tag) {
  if (selectedTaskIds.value.size === 0) {
    return
  }

  try {
    const taskIds = Array.from(selectedTaskIds.value)
    await api.post('/tasks/batch/tags/remove', {
      task_ids: taskIds,
      tags: [tag]
    })

    emit('refresh')
  } catch (error) {
    console.error('批次移除標籤失敗:', error)
    alert('批次移除標籤失敗：' + (error.response?.data?.detail || error.message))
  }
}

onMounted(() => {
  fetchTagColors()
  fetchTagOrder()
})
</script>

<style scoped>
.task-list {
  margin-top: 24px;
  margin-left: 15px;
  margin-bottom: 20px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.list-header h2 {
  font-size: 24px;
  color: #2d2d2d;
  text-shadow: 0 2px 4px rgba(139, 69, 19, 0.2);
  font-weight: 700;
}

.btn-icon {
  padding: 10px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: transparent;
  color: var(--nav-recent-bg);
  box-shadow: none;
}

.btn-icon:hover {
  transform: translateY(-1px) rotate(180deg);
  background: transparent;
  color: var(--nav-recent-bg);
  box-shadow: none;
}

.btn-icon svg {
  transition: transform 0.3s ease;
}

/* 標籤篩選區 */
.filter-section {
  background: var(--neu-bg);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 20px;
  box-shadow: var(--neu-shadow-inset);
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}


.filter-icon {
  color: rgba(119, 150, 154, 0.8);
  flex-shrink: 0;
}

.filter-label {
  font-size: 13px;
  font-weight: 600;
  color: rgba(45, 45, 45, 0.7);
}

.filter-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-left: auto;
  flex-shrink: 0;
}

.btn-edit-filter {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #ffffff;
  background: rgb(119, 150, 154);
  border: 1px solid rgb(119, 150, 154);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-edit-filter:hover {
  background: #336774;
  border-color: rgba(119, 150, 154, 0.5);
  transform: translateY(-1px);
}

.btn-save-filter {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  color: white;
  background: #838A2D;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-save-filter:hover {
  background: #5B622E;
  transform: translateY(-1px);
}

.btn-cancel-filter {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-cancel-filter:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
  transform: translateY(-1px);
}

.btn-clear-filter {
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-clear-filter:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
  transform: translateY(-1px);
}

.filter-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  flex: 1;
  align-items: center;
}

.filter-tag-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
}

.filter-tag-item.editing {
  background: rgba(255, 255, 255, 0.5);
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px dashed rgba(221, 132, 72, 0.2);
  cursor: move;
  transition: all 0.2s;
}

.filter-tag-item.dragging {
  opacity: 0.5;
  transform: scale(0.95);
}

.filter-tag-item.drag-over {
  background: rgba(119, 150, 154, 0.15);
  border-color: rgba(119, 150, 154, 0.5);
  transform: scale(1.02);
}

.drag-handle {
  display: flex;
  align-items: center;
  color: rgba(119, 150, 154, 0.6);
  cursor: move;
  padding: 2px;
}

.drag-handle:hover {
  color: #77969A;
}

.tag-order-controls {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.btn-move-tag {
  width: 20px;
  height: 16px;
  padding: 0;
  background: rgba(119, 150, 154, 0.1);
  border: 1px solid rgba(119, 150, 154, 0.3);
  border-radius: 4px;
  color: #77969A;
  font-size: 10px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-move-tag:hover:not(:disabled) {
  background: rgba(119, 150, 154, 0.2);
  border-color: rgba(119, 150, 154, 0.5);
  transform: scale(1.1);
}

.btn-move-tag:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.filter-tag-btn {
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  border: none;
  border-radius: 0;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
}

.filter-tag-btn:disabled {
  cursor: default;
  opacity: 0.8;
}

/* 篩選標籤編輯輸入框 */
.filter-tag-input {
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  border: 2px solid var(--neu-primary);
  border-radius: 12px;
  outline: none;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-inset);
  min-width: 100px;
  transition: all 0.2s;
}

.filter-tag-input:focus {
  box-shadow: var(--neu-shadow-inset-hover);
}

.filter-tag-btn:hover:not(.active):not(:disabled) {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
}

.filter-tag-btn.active {
  font-weight: 600;
  box-shadow: var(--neu-shadow-btn-active);
  border-bottom: 2px solid var(--nav-recent-bg);
}

.filter-tag-btn.active:hover:not(:disabled) {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
}

/* 標籤顏色選擇器 */
.color-picker-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.1);
  z-index: 9998;
  cursor: default;
}

.tag-color-picker-wrapper {
  position: relative;
}

.btn-color-picker {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  background: rgba(119, 150, 154, 0.1);
  border: 1px solid rgba(119, 150, 154, 0.3);
  border-radius: 50%;
  color: #77969A;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-color-picker:hover {
  background: rgba(119, 150, 154, 0.2);
  border-color: rgba(119, 150, 154, 0.5);
  transform: scale(1.1);
}

.color-picker-popup {
  position: fixed;
  background: white;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  z-index: 9999;
  min-width: 220px;
}

.color-picker-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 600;
  color: rgba(45, 45, 45, 0.8);
}

.btn-close-picker {
  width: 20px;
  height: 20px;
  padding: 0;
  background: rgba(239, 68, 68, 0.1);
  border: none;
  border-radius: 4px;
  color: #ef4444;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-close-picker:hover {
  background: rgba(239, 68, 68, 0.2);
}

.color-input {
  width: 100%;
  height: 40px;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 10px;
}

.preset-colors {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
}

.preset-color-btn {
  width: 32px;
  height: 32px;
  border: 2px solid rgba(255, 255, 255, 0.8);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.preset-color-btn:hover {
  transform: scale(1.1);
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.2);
  border-color: white;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: rgba(45, 45, 45, 0.5);
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(15px);
  border-radius: 16px;
  border: 1px dashed rgba(255, 250, 235, 0.6);
}

.empty-state p:first-child {
  font-size: 18px;
  font-weight: 500;
  margin-bottom: 8px;
  color: rgba(45, 45, 45, 0.7);
}

.text-muted {
  font-size: 14px;
}

.tasks {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.task-wrapper {
  margin-bottom: 0;
}

.task-item {
  padding: 20px;
  transition: all 0.3s;
  position: relative;
  z-index: 1;
  background: var(--upload-bg);
  clip-path: polygon(
    25px 0,
    100% 0,
    100% calc(100% - 25px),
    calc(100% - 25px) 100%,
    0 100%,
    0 25px
  );
}

.task-wrapper:hover .task-item {
  box-shadow: 0 4px 12px rgba(221, 132, 72, 0.15);
  transform: translateY(-2px);
}

.task-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}

.task-info {
  flex: 1;
}

.task-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: #000000 0.5px solid;
}

.task-header h3 {
  font-size: 16px;
  color: #2d2d2d;
  margin: 0;
}

.task-divider {
  font-size: 14px;
  font-weight: 300;
  color: rgba(0, 0, 0, 0.3);
  margin: 0 -4px;
}

.task-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: rgba(45, 45, 45, 0.6);
  margin-bottom: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.task-meta .meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.task-meta .meta-item svg {
  flex-shrink: 0;
  opacity: 0.7;
}

.badge-diarize {
  padding: 2px 8px;
  background: rgba(246, 156, 92, 0.1);
  border: 1px solid rgba(246, 141, 92, 0.3);
  border-radius: 4px;
  color: rgba(217, 108, 40, 0.9);
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
}

.badge-diarize:hover {
  background: rgba(246, 138, 92, 0.15);
  border-color: rgba(246, 146, 92, 0.5);
  transform: translateY(-1px);
}

/* 展開/收起按鈕 */
.btn-toggle-details {
  padding: 4px 10px;
  background: rgba(221, 132, 72, 0.08);
  border: 1px solid rgba(221, 132, 72, 0.25);
  border-radius: 4px;
  color: var(--electric-primary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  margin-left: auto;
}

.btn-toggle-details:hover {
  background: rgba(221, 132, 72, 0.15);
  border-color: var(--electric-primary);
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(221, 132, 72, 0.2);
}

.task-progress {
  margin-top: 12px;
}

.progress-bar {
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #dd8448 0%, #f59e42 100%);
  transition: width 0.5s ease;
  border-radius: 3px;
}

.progress-text {
  font-size: 13px;
  color: rgba(45, 45, 45, 0.8);
  display: flex;
  align-items: center;
  gap: 8px;
}

.estimate-time {
  color: #a0522d;
  font-weight: 500;
}

.progress-percentage {
  color: var(--electric-primary);
  font-weight: 600;
  margin-left: 8px;
}

.diarization-status {
  font-size: 12px;
  margin-top: 6px;
  padding: 6px 10px;
  border-radius: 4px;
  font-weight: 500;
  color: rgba(45, 45, 45, 0.7);
}

.diarization-status.status-running {
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
}

.diarization-status.status-completed {
  background: rgba(221, 132, 72, 0.12);
  border: 1px solid rgba(221, 132, 72, 0.3);
}

.diarization-status.status-failed {
  background: rgba(221, 132, 72, 0.08);
  border: 1px solid rgba(221, 100, 50, 0.3);
}

.processing-chunks {
  font-size: 12px;
  color: rgba(45, 45, 45, 0.7);
  margin-top: 6px;
  padding: 6px 10px;
  background: rgba(59, 130, 246, 0.08);
  border-radius: 4px;
  border: 1px solid rgba(59, 130, 246, 0.15);
}

.task-result {
  margin-top: 8px;
  padding: 8px 12px;
  background: #89916B26;
  border: 1px solid #89916B4d;
  border-radius: 6px;
  font-size: 14px;
  color: rgba(45, 45, 45, 0.7);
}

.task-result .duration {
  margin-top: 4px;
  font-size: 13px;
  opacity: 0.9;
}

.task-error {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  font-size: 14px;
  color: #f87171;
}

.task-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-end;
}

/* 保留音檔 Toggle Switch */
.keep-audio-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  /* margin-right: 2px; */
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
  padding-right: 5px;
  position: relative;
}

.toggle-label:hover .toggle-slider {
  transform: scale(1.05);
}

/* Toggle Switch 容器 */
.toggle-switch-wrapper {
  position: relative;
  width: 44px;
  height: 24px;
  display: inline-block;
}

/* 隱藏原生 checkbox */
.toggle-input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}

/* Toggle Slider */
.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #ccc;
  transition: all 0.3s ease;
  border-radius: 24px;
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
}

/* Checked 狀態 */
.toggle-input:checked + .toggle-slider {
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%);
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1), 0 0 8px rgba(221, 132, 72, 0.3);
}

.toggle-input:checked + .toggle-slider:before {
  transform: translateX(20px);
}

/* Disabled 狀態 */
.toggle-input:disabled + .toggle-slider {
  opacity: 0.5;
  cursor: not-allowed;
  background-color: #ddd;
}

.toggle-input:disabled + .toggle-slider:before {
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
}

/* Hover 效果 */
.toggle-label:hover .toggle-slider:not(.toggle-input:disabled + .toggle-slider) {
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2), 0 0 4px rgba(0, 0, 0, 0.1);
}

.toggle-label:hover .toggle-input:checked + .toggle-slider {
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.1), 0 0 12px rgba(221, 132, 72, 0.4);
}

/* 鎖頭 Icon 共用樣式 */
.lock-icon {
  position: absolute;
  transition: all 0.3s ease;
  z-index: 1;
  pointer-events: none;
}

/* 解鎖圖標（未選中時） */
.unlock-icon {
  left: 6px;
  color: #888;
  opacity: 1;
}

/* 上鎖圖標（選中時） */
.locked-icon {
  right: 6px;
  color: rgb(177, 79, 22);
  filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.3));
  opacity: 0;
}

/* 未選中狀態：顯示解鎖，隱藏上鎖 */
.toggle-input:not(:checked) + .toggle-slider .unlock-icon {
  opacity: 1;
}

.toggle-input:not(:checked) + .toggle-slider .locked-icon {
  opacity: 0;
}

/* 選中狀態：隱藏解鎖，顯示上鎖 */
.toggle-input:checked + .toggle-slider .unlock-icon {
  opacity: 0;
}

.toggle-input:checked + .toggle-slider .locked-icon {
  opacity: 1;
}

/* Disabled 時的鎖頭 */
.toggle-input:disabled + .toggle-slider .lock-icon {
  opacity: 0.4;
}

.newest-badge {
  position: absolute;
  top: -14px;
  right: -10px;
  padding: 1px 4px;
  font-size: 11px;
  font-weight: 600;
  background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
  color: white;
  border-radius: 4px;
  box-shadow: 0 2px 4px rgba(255, 107, 107, 0.3);
  pointer-events: none;
}

/* 三聯按鈕組 - Neumorphism 風格 */
.btn-group {
  display: inline-flex;
  border-radius: 12px;
  overflow: visible;
  gap: 8px;
  background: transparent;
}

.btn-group .btn {
  border-radius: 12px;
  margin: 0;
  position: relative;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn-sm);
  transition: all 0.3s ease;
}

.btn-group .btn:not(:last-child) {
  border-right: none;
}

.btn-group-left {
  border-radius: 12px !important;
}

.btn-group-middle {
  border-radius: 12px !important;
}

.btn-group-right {
  border-radius: 12px !important;
}

/* 確保三聯組中的按鈕 hover 效果不會被覆蓋 */
.btn-group .btn:hover {
  z-index: 1;
  box-shadow: var(--neu-shadow-btn-hover-sm);
  transform: translateY(-2px);
}

.btn-group .btn:active {
  box-shadow: var(--neu-shadow-btn-active-sm);
  transform: translateY(0);
}

/* 圖標按鈕樣式 */
.btn-icon {
  min-width: 52px;
  width: 52px;
  height: 36px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.btn-icon svg {
  flex-shrink: 0;
}

/* 瀏覽按鈕 - Neumorphism 風格 */
.btn-view {
  background: var(--neu-bg);
  color: #2d2d2d;
  border: none;
  font-weight: 500;
}

.btn-view:hover {
  color: #4a6680;
}

.btn-download {
  background: var(--neu-bg);
  color: #2d2d2d;
  border: none;
  font-weight: 500;
}

.btn-download:hover {
  color: #4a6680;
}

/* 刪除按鈕 - Neumorphism 風格 */
.task-actions .btn-danger {
  background: var(--neu-bg);
  color: #d64545;
  border: none;
  font-weight: 500;
}

.task-actions .btn-danger:hover {
  color: #b83939;
}

/* 標籤樣式 */
.task-tags-section {
  margin-top: 12px;
  margin-bottom: 4px;
}

.task-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.task-tags-display .task-tags {
  margin-top: 0;
}

.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  color: white;
  background: #667eea;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  transition: all 0.2s ease;
  cursor: default;
}

.tag-badge:hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.15);
}

.tag-badge.editable {
  padding-right: 8px;
  cursor: pointer;
}

.tag-badge.editable:hover {
  opacity: 0.9;
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.2);
}

/* 標籤文字編輯狀態 */
.tag-badge-editing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  color: white;
  background: #667eea;
  box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
}

.tag-text-input {
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 500;
  color: #2d2d2d;
  min-width: 80px;
  outline: none;
  transition: all 0.2s ease;
}

.tag-text-input:focus {
  background: white;
  border-color: rgba(255, 255, 255, 0.8);
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.3);
}

.save-tag-text,
.cancel-tag-text {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 4px;
  color: white;
  font-size: 12px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s ease;
}

.save-tag-text:hover {
  background: rgba(76, 175, 80, 0.9);
  border-color: rgba(76, 175, 80, 1);
  transform: scale(1.1);
}

.cancel-tag-text:hover {
  background: rgba(244, 67, 54, 0.9);
  border-color: rgba(244, 67, 54, 1);
  transform: scale(1.1);
}

.btn-edit-tags {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 8px;
  background: rgba(119, 150, 154, 0.1);
  border: 1px solid #77969a4d;
  border-radius: 8px;
  color: #77969A;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 12px;
}

.btn-edit-tags:hover {
  background: rgba(119, 150, 154, 0.2);
  border-color: rgba(119, 150, 154, 0.5);
  transform: translateY(-1px);
}

.btn-add-tags {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  background: rgba(102, 126, 234, 0.1);
  border: 1px dashed rgba(102, 126, 234, 0.4);
  border-radius: 8px;
  color: #667eea;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 12px;
  font-weight: 500;
}

.btn-add-tags:hover {
  background: rgba(102, 126, 234, 0.15);
  border-color: rgba(102, 126, 234, 0.6);
  transform: translateY(-1px);
}

/* 標籤編輯模式 */
.tag-edit-mode {
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(221, 132, 72, 0.2);
  border-radius: 8px;
  padding: 12px;
}

.tag-edit-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.tag-edit-label {
  font-size: 12px;
  font-weight: 600;
  color: rgba(45, 45, 45, 0.7);
}

.tag-edit-actions {
  display: flex;
  gap: 6px;
}

.btn-tag-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 4px;
  font-size: 14px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-tag-action.btn-save {
  background: #43e97b;
  color: white;
}

.btn-tag-action.btn-save:hover {
  background: #38d66a;
  transform: translateY(-1px);
}

.btn-tag-action.btn-cancel {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

.btn-tag-action.btn-cancel:hover {
  background: rgba(239, 68, 68, 0.25);
  transform: translateY(-1px);
}

.tag-input-wrapper-inline {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
}

.tag-input-inline {
  flex: 1;
  padding: 6px 10px;
  font-size: 13px;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  background: white;
  color: #2d2d2d;
  outline: none;
  transition: all 0.2s;
}

.tag-input-inline:focus {
  border-color: #77969A;
  box-shadow: 0 0 0 2px rgba(119, 150, 154, 0.1);
}

.available-tags-section {
  margin-bottom: 12px;
  padding: 10px;
  background: rgba(119, 150, 154, 0.05);
  border: 1px dashed rgba(119, 150, 154, 0.2);
  border-radius: 6px;
}

.available-tags-label {
  font-size: 11px;
  font-weight: 600;
  color: rgba(45, 45, 45, 0.6);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.available-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.available-tag-btn {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 500;
  border: 1.5px solid;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  background: transparent;
}

.available-tag-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
  filter: brightness(0.95);
}

.btn-add-tag-inline {
  width: 32px;
  height: 32px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #77969A;
  border: none;
  border-radius: 6px;
  color: white;
  font-size: 18px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-add-tag-inline:hover:not(:disabled) {
  background: #336774;
  transform: translateY(-1px);
}

.btn-add-tag-inline:disabled {
  background: rgba(119, 150, 154, 0.4);
  cursor: not-allowed;
}

.remove-tag-inline {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  margin: 0;
  background: rgba(255, 255, 255, 0.3);
  border: none;
  border-radius: 50%;
  color: white;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
}

.remove-tag-inline:hover {
  background: rgba(239, 68, 68, 0.8);
}

/* ==== 批次編輯模式樣式 ==== */
/* Header 按鈕組 */
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-batch-edit {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.3s ease;
  background: transparent;
  color: var(--nav-recent-bg);
  box-shadow: none;
}

.btn-batch-edit:hover {
  background: transparent;
  color: var(--nav-recent-bg);
  box-shadow: none;
}

.btn-batch-edit.active {
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%);
  color: white;
  border-color: var(--electric-primary);
}

.btn-batch-edit.active:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(221, 132, 72, 0.3);
}

/* 批次工具列 */
.batch-toolbar {
  margin-bottom: 20px;
  padding: 16px;
  background: linear-gradient(135deg, rgba(221, 132, 72, 0.08) 0%, rgba(184, 118, 45, 0.05) 100%);
  border: 2px solid rgba(221, 132, 72, 0.2);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(221, 132, 72, 0.1);
}

.batch-toolbar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  gap: 16px;
  flex-wrap: wrap;
}

.batch-header-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
  min-width: 0;
}

.batch-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.btn-batch-select-all {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 6px 12px;
  background: white;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  color: #2d2d2d;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-batch-select-all:hover {
  background: rgba(221, 132, 72, 0.1);
  border-color: var(--electric-primary);
}

.btn-batch-select-all input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.batch-selection-count {
  font-size: 14px;
  font-weight: 600;
  color: var(--electric-primary);
}

/* 批次操作按鈕 */
.batch-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid rgba(221, 132, 72, 0.2);
}

.batch-action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 批次標籤管理區域 */
.batch-tags-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(221, 132, 72, 0.15);
  border-radius: 8px;
}

.batch-tags-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.batch-tags-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.batch-tags-label .label-text {
  font-weight: 600;
  color: #2d2d2d;
}

.batch-tags-label .label-hint {
  font-weight: 400;
  color: rgba(45, 45, 45, 0.6);
  font-size: 12px;
}

.batch-tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.batch-tag-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: 2px solid;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.batch-tag-btn .tag-action-icon {
  flex-shrink: 0;
}

/* 已加入標籤（可移除） */
.batch-tag-btn.common-tag {
  color: white;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.batch-tag-btn.common-tag:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
  filter: brightness(1.1);
}

.batch-tag-btn.common-tag:active {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

/* 候選標籤（可加入） */
.batch-tag-btn.candidate-tag {
  background-color: white;
}

.batch-tag-btn.candidate-tag:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
  filter: brightness(0.95);
}

.batch-tag-btn.candidate-tag:active {
  transform: translateY(0);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.batch-tags-empty {
  padding: 16px;
  text-align: center;
  color: rgba(45, 45, 45, 0.5);
  font-size: 13px;
  background: rgba(221, 132, 72, 0.05);
  border-radius: 6px;
  border: 1px dashed rgba(221, 132, 72, 0.2);
}

/* 手動輸入標籤 */
.batch-manual-input {
  padding-top: 8px;
  border-top: 1px solid rgba(221, 132, 72, 0.15);
}

.batch-manual-input-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.batch-manual-input-field {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  font-size: 14px;
  outline: none;
  transition: all 0.2s;
  background: white;
}

.batch-manual-input-field:focus {
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.batch-manual-input-field::placeholder {
  color: rgba(45, 45, 45, 0.4);
}

.btn-batch-manual-add {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  flex-shrink: 0;
}

.btn-batch-manual-add:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(221, 132, 72, 0.3);
}

.btn-batch-manual-add:active:not(:disabled) {
  transform: translateY(0);
}

.btn-batch-manual-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ============================================
   緊湊型批次標籤管理區域
   ============================================ */

.batch-tags-section-compact {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0;
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(221, 132, 72, 0.15);
  border-radius: 8px;
  overflow: hidden;
  max-height: 240px;
  transition: max-height 0.3s ease;
}

.batch-tags-section-compact.collapsed {
  max-height: 48px;
}

/* 標籤區域標題 */
.batch-tags-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: rgba(221, 132, 72, 0.08);
  border-bottom: 1px solid rgba(221, 132, 72, 0.1);
  gap: 12px;
}

.batch-tags-info {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.batch-tags-info svg {
  flex-shrink: 0;
  stroke: var(--electric-primary);
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.tags-title {
  font-size: 14px;
  font-weight: 600;
  color: #2d2d2d;
  flex-shrink: 0;
}

.tags-stats {
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  white-space: nowrap;
}

.btn-collapse {
  flex-shrink: 0;
  padding: 6px 12px;
  background: white;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  color: var(--electric-primary);
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.btn-collapse:hover {
  background: rgba(221, 132, 72, 0.1);
  border-color: var(--electric-primary);
  transform: translateY(-1px);
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.btn-collapse:active {
  transform: translateY(0);
  box-shadow: none;
}

/* 標籤內容區域 */
.batch-tags-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 16px;
  overflow: hidden;
}

/* 標籤 Pills 容器 */
.tags-pills-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  background: var(--neu-bg);
  border-radius: 12px;
  box-shadow: var(--neu-shadow-inset);
}

.tags-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  padding: 4px 0;
}

.tags-pills-list {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  overflow-x: auto;
  overflow-y: hidden;
  max-height: 80px;
  padding: 4px 0;
  scrollbar-width: thin;
  scrollbar-color: rgba(221, 132, 72, 0.3) transparent;
}

.tags-pills-list::-webkit-scrollbar {
  height: 6px;
}

.tags-pills-list::-webkit-scrollbar-track {
  background: rgba(221, 132, 72, 0.05);
  border-radius: 3px;
}

.tags-pills-list::-webkit-scrollbar-thumb {
  background: rgba(221, 132, 72, 0.3);
  border-radius: 3px;
}

.tags-pills-list::-webkit-scrollbar-thumb:hover {
  background: rgba(221, 132, 72, 0.5);
}

/* 標籤 Pill 按鈕 */
.tag-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border: none;
  border-radius: 16px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  flex-shrink: 0;
  position: relative;
  background: var(--neu-bg);
  box-shadow: var(--neu-shadow-btn);
}

.tag-pill:hover {
  box-shadow: var(--neu-shadow-btn-hover);
  transform: translateY(-2px);
}

.tag-pill:active {
  box-shadow: var(--neu-shadow-btn-active);
  transform: translateY(0);
}

/* 已加入的標籤 */
.tag-pill.tag-added {
  font-weight: 600;
  box-shadow: var(--neu-shadow-btn);
}

.tag-pill.tag-added svg {
  stroke-width: 2.5;
}

.tag-pill.tag-added:hover {
  box-shadow: var(--neu-shadow-btn-hover);
}

.tag-pill.tag-added:active {
  box-shadow: var(--neu-shadow-btn-active);
}

/* 可用的標籤 */
.tag-pill.tag-available {
  background: var(--neu-bg);
  opacity: 0.7;
  font-weight: 500;
}

.tag-pill.tag-available:hover {
  opacity: 1;
}

/* Pill 圖標 */
.pill-icon {
  flex-shrink: 0;
  stroke: currentColor;
  fill: none;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.tag-pill.tag-added .pill-icon {
  stroke: white;
}

/* 手動輸入區域（緊湊版） */
.batch-manual-input-compact {
  display: flex;
  gap: 8px;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid rgba(221, 132, 72, 0.15);
}

.manual-input-field {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  transition: all 0.2s;
  background: white;
}

.manual-input-field:focus {
  border-color: var(--electric-primary);
  box-shadow: 0 0 0 3px rgba(221, 132, 72, 0.1);
}

.manual-input-field::placeholder {
  color: rgba(45, 45, 45, 0.4);
  font-size: 12px;
}

.btn-manual-add {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  background: linear-gradient(135deg, var(--electric-primary) 0%, #b8762d 100%);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  flex-shrink: 0;
}

.btn-manual-add:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(221, 132, 72, 0.3);
}

.btn-manual-add:active:not(:disabled) {
  transform: translateY(0);
}

.btn-manual-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 批次操作按鈕 */
.btn-batch-action {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: white;
  border: 1px solid rgba(221, 132, 72, 0.3);
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  color: #2d2d2d;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.btn-batch-action:hover {
  border-color: var(--electric-primary);
  background: rgba(221, 132, 72, 0.1);
}

.btn-batch-delete {
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.3);
}

.btn-batch-delete:hover {
  background: rgba(220, 38, 38, 0.1);
  border-color: #dc2626;
}

/* 批次編輯模式下的任務列表 - 統一列表樣式 */
.tasks.batch-mode {
  gap: 0;
  background: white;
  border-radius: 12px;
  border: 2px solid rgba(221, 132, 72, 0.15);
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(221, 132, 72, 0.08);
}

.tasks.batch-mode .task-wrapper {
  margin-bottom: 0;
  padding: 0;
  border-radius: 0;
  background: transparent;
}

.tasks.batch-mode .task-wrapper:not(:last-child) .task-item {
  border-bottom: 1px solid rgba(221, 132, 72, 0.1);
}

.tasks.batch-mode .task-wrapper:hover .task-item {
  box-shadow: none;
  transform: none;
  background: rgba(221, 132, 72, 0.03);
}

/* 任務項目批次編輯模式 */
.task-item.batch-edit-mode {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
}

.task-item.batch-edit-mode .task-main {
  flex: 1;
  min-width: 0;
}

/* 批次編輯模式下的任務資訊佈局 - 橫向緊湊 */
.task-item.batch-edit-mode .task-info {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.task-item.batch-edit-mode .task-header {
  margin-bottom: 0;
  flex-shrink: 0;
}

.task-item.batch-edit-mode .task-header h3 {
  font-size: 14px;
  margin: 0;
}

.task-item.batch-edit-mode .task-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 0;
  font-size: 12px;
  color: rgba(45, 45, 45, 0.6);
  flex-shrink: 0;
}

.task-item.batch-edit-mode .task-meta span {
  white-space: nowrap;
}

.task-item.batch-edit-mode .task-tags-section {
  margin-top: 0;
  margin-bottom: 0;
  flex-shrink: 0;
}

.task-item.batch-edit-mode .task-tags {
  gap: 6px;
}

.task-item.batch-edit-mode .task-tag {
  font-size: 11px;
  padding: 3px 8px;
}

/* 批次編輯模式下隱藏個別任務的標籤編輯按鈕 */
.task-item.batch-edit-mode .btn-edit-tags,
.task-item.batch-edit-mode .btn-add-tags {
  display: none;
}

/* 批次編輯模式下隱藏非必要資訊 */
.task-item.batch-edit-mode .task-actions {
  display: none;
}

.task-item.batch-edit-mode .task-progress {
  display: none;
}

.task-item.batch-edit-mode .task-result {
  display: none;
}

/* .task-item.batch-edit-mode .task-header .badge {
  display: none;
} */

.task-item.batch-edit-mode .badge-diarize {
  display: none;
}

.batch-select-checkbox {
  display: flex;
  align-items: flex-start;
  padding-top: 4px;
  flex-shrink: 0;
}

.batch-checkbox {
  width: 20px;
  height: 20px;
  cursor: pointer;
  accent-color: var(--electric-primary);
}

/* 響應式調整 */
@media (max-width: 768px) {
  .batch-toolbar {
    padding: 12px;
  }

  .batch-toolbar-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .batch-header-left {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .batch-header-right {
    width: 100%;
  }

  .batch-header-right .btn-batch-delete {
    width: 100%;
    justify-content: center;
  }

  .batch-actions {
    flex-direction: column;
    align-items: stretch;
    gap: 16px;
  }

  .batch-action-group {
    width: 100%;
  }

  .batch-tags-section {
    width: 100%;
  }

  .btn-batch-action {
    width: 100%;
    justify-content: center;
  }

  /* 緊湊型標籤區域響應式 */
  .batch-tags-section-compact {
    width: 100%;
  }

  .batch-tags-header {
    padding: 10px 12px;
    flex-wrap: wrap;
  }

  .batch-tags-info {
    flex-wrap: wrap;
  }

  .tags-title {
    font-size: 13px;
  }

  .tags-stats {
    font-size: 11px;
  }

  .btn-collapse {
    font-size: 11px;
    padding: 5px 10px;
  }

  .batch-tags-content {
    padding: 10px 12px;
  }

  .tags-pills-list {
    flex-wrap: wrap;
    max-height: none;
  }

  .tag-pill {
    height: 28px;
    padding: 0 12px;
    font-size: 12px;
  }

  .batch-manual-input-compact {
    flex-direction: column;
    align-items: stretch;
  }

  .btn-manual-add {
    width: 100%;
    justify-content: center;
  }
}
</style>
