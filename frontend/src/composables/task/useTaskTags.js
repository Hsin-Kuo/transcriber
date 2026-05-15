import { ref, computed } from 'vue'
import api from '../../utils/api'

/**
 * 預設顏色選項
 * 這些顏色值對應 assets/colors.css 中的 --tag-color-1 到 --tag-color-20
 * 保持為 hex 值是因為需要存儲到數據庫和動態設置樣式
 */
export const presetColors = [
  '#667eea', '#f093fb', '#4facfe', '#43e97b', '#fa709a',
  '#feca57', '#48dbfb', '#ff6b6b', '#ee5a6f', '#c44569',
  '#a29bfe', '#fd79a8', '#fdcb6e', '#00b894', '#0984e3',
  '#6c5ce7', '#e17055', '#74b9ff', '#55efc4', '#ffeaa7'
]

/**
 * 默認顏色（用於根據標籤名稱 hash 生成顏色）
 * 對應 colors.css 中的標籤預設色
 */
const defaultColors = [
  '#667eea', // 紫藍 --tag-color-1
  '#f093fb', // 粉紫 --tag-color-2
  '#4facfe', // 天藍 --tag-color-3
  '#43e97b', // 青綠 --tag-color-4
  '#fa709a', // 粉紅 --tag-color-5
  '#feca57', // 橘黃 --tag-color-6
  '#48dbfb', // 青藍 --tag-color-7
  '#ff6b6b', // 珊瑚紅 --tag-color-8
  '#ee5a6f', // 玫瑰紅 --tag-color-9
  '#c44569', // 暗紅 --tag-color-10
]

// ===== 全局共享狀態 =====
// 這些 ref 在所有組件間共享，確保標籤顏色一致性
const globalTagColors = ref({})
const globalTagsData = ref([]) // 存儲完整的標籤信息（包含 ID）
const globalCustomTagOrder = ref([])

/**
 * Task Tags Composable
 * 管理任務標籤的共享狀態和邏輯
 */
export function useTaskTags($t) {
  // ===== 狀態（使用全局共享實例） =====
  const tagColors = globalTagColors
  const tagsData = globalTagsData
  const customTagOrder = globalCustomTagOrder

  // ===== 計算屬性 =====

  /**
   * 從任務列表中提取所有唯一標籤
   * @param {Array} tasks - 任務列表
   * @returns {ComputedRef<Array>} 排序後的標籤數組
   */
  function getAllTags(tasks) {
    return computed(() => {
      const tags = new Set()
      tasks.value?.forEach(task => {
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
  }

  // ===== API 函數 =====

  /**
   * 從後端獲取標籤顏色
   */
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

      // 同時更新標籤順序（tags 已按 order 欄位排序）
      if (tags.length > 0) {
        customTagOrder.value = tags.map(tag => tag.name)
      }
    } catch (error) {
      console.error(($t ? $t('taskList.errorFetchTagColors') : 'Error fetching tag colors') + ':', error)
    }
  }

  /**
   * 從後端獲取標籤順序
   * 注意：這個函數現在從 tagsData 中提取名稱順序（因為 tagsData 已按 order 排序）
   */
  async function fetchTagOrder() {
    try {
      // 如果 tagsData 已經有數據，直接從中提取名稱順序
      if (tagsData.value.length > 0) {
        customTagOrder.value = tagsData.value.map(tag => tag.name)
        console.log('✅ ' + ($t ? $t('taskList.logLoadedTagOrder') : 'Loaded custom tag order'), tagsData.value.length, ($t ? $t('taskList.logTagCount') : 'tags'))
        return
      }

      // 如果 tagsData 尚未加載，則先獲取標籤數據
      const response = await api.get('/tags')
      const tags = response.data || []

      if (tags.length > 0) {
        tagsData.value = tags
        customTagOrder.value = tags.map(tag => tag.name)
        console.log('✅ ' + ($t ? $t('taskList.logLoadedTagOrder') : 'Loaded custom tag order'), tags.length, ($t ? $t('taskList.logTagCount') : 'tags'))
      }
    } catch (error) {
      console.error(($t ? $t('taskList.errorFetchTagOrder') : 'Error fetching tag order') + ':', error)
    }
  }

  /**
   * 保存標籤順序到後端
   * @param {Array} tagIds - 標籤 ID 數組
   */
  async function saveTagOrder(tagIds) {
    try {
      await api.put('/tags/order', {
        tag_ids: tagIds
      })
      console.log('✅ ' + ($t ? $t('taskList.successSaveTagOrder') : 'Tag order saved successfully'))
    } catch (error) {
      console.error(($t ? $t('taskList.errorSaveTagOrder') : 'Error saving tag order') + ':', error)
      throw error
    }
  }

  /**
   * 更新標籤顏色（本地）
   * 只更新本地狀態，不發送 API 請求
   * @param {string} tagName - 標籤名稱
   * @param {string} color - 顏色代碼
   */
  function updateTagColorLocal(tagName, color) {
    // 只更新本地顏色狀態
    tagColors.value = { ...tagColors.value, [tagName]: color }
  }

  /**
   * 保存標籤顏色到後端
   * @param {string} tagName - 標籤名稱
   * @param {string} color - 顏色代碼
   */
  async function saveTagColor(tagName, color) {
    try {
      // 調試：查看 tagsData 的內容
      console.log('🔍 saveTagColor - 查找標籤:', tagName)
      console.log('🔍 tagsData 內容:', JSON.stringify(tagsData.value.map(t => ({ name: t.name, id: t._id || t.tag_id }))))

      // 從 tagsData 中找到對應的標籤對象
      let tagObj = tagsData.value.find(t => t.name === tagName)

      // 如果標籤不存在於後端，先創建它
      if (!tagObj) {
        console.log('🏷️ 標籤不存在於 tagsData，正在創建:', tagName)
        const response = await api.post('/tags', {
          name: tagName,
          color: color
        })
        tagObj = response.data

        // 將新標籤添加到 tagsData
        tagsData.value = [...tagsData.value, tagObj]
        console.log('✅ 標籤創建成功:', tagObj)
        return
      }

      // 使用正確的 API 端點和標籤 ID（優先使用 tag_id，即 UUID 格式）
      await api.put(`/tags/${tagObj.tag_id || tagObj._id}`, {
        name: tagObj.name,
        color: color,
        description: tagObj.description || null
      })
    } catch (error) {
      console.error(($t ? $t('taskList.errorUpdateTagColor') : 'Error updating tag color') + ':', error)
      throw error
    }
  }

  /**
   * 更新標籤顏色（向後兼容，立即保存）
   * @param {string} tagName - 標籤名稱
   * @param {string} color - 顏色代碼
   */
  async function updateTagColor(tagName, color) {
    // 先更新本地狀態
    updateTagColorLocal(tagName, color)
    // 然後保存到後端
    await saveTagColor(tagName, color)
  }

  /**
   * 刪除標籤
   *
   * 後端會以 update_many + $pull 從所有任務移除該標籤（cascade delete）。
   * 成功後 local 移除共享狀態中該 tag 的痕跡，不重新 fetch tagColors，
   * 以保留其他 tag 的 pendingColorChanges 等暫存變更。
   *
   * @param {string} tagName - 要刪除的標籤名稱
   * @returns {Promise<boolean>} 是否成功刪除
   */
  async function deleteTag(tagName) {
    let tagObj = tagsData.value.find(t => t.name === tagName)

    // 若 tag 尚未在 tags collection（純由 task.tags 推導），先建立才能走 cascade delete
    if (!tagObj) {
      const response = await api.post('/tags', {
        name: tagName,
        color: getTagColor(tagName)
      })
      tagObj = response.data
    }

    const tagId = tagObj.tag_id || tagObj._id
    await api.delete(`/tags/${tagId}`)
    _removeTagFromLocalState(tagName)
    return true
  }

  /**
   * 從共享狀態移除指定標籤的所有痕跡（local only）
   * @param {string} tagName
   */
  function _removeTagFromLocalState(tagName) {
    tagsData.value = tagsData.value.filter(t => t.name !== tagName)

    if (tagColors.value[tagName]) {
      const next = { ...tagColors.value }
      delete next[tagName]
      tagColors.value = next
    }

    if (customTagOrder.value.includes(tagName)) {
      customTagOrder.value = customTagOrder.value.filter(t => t !== tagName)
    }
  }

  /**
   * 重命名標籤（更新所有使用該標籤的任務）
   * @param {string} oldTag - 舊標籤名稱
   * @param {string} newTag - 新標籤名稱
   * @param {Array} tasks - 任務列表
   */
  async function renameTag(oldTag, newTag, tasks) {
    try {
      // 更新所有任務中的標籤
      const tasksToUpdate = tasks.filter(task =>
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

      // 更新標籤顏色
      if (tagColors.value[oldTag]) {
        const oldColor = tagColors.value[oldTag]
        tagColors.value[newTag] = oldColor
        delete tagColors.value[oldTag]
        // 保存新標籤的顏色
        await updateTagColor(newTag, oldColor)
      }

      console.log('✅ ' + ($t ? $t('taskList.successRenameTag', { oldTag, newTag }) : `Tag renamed from ${oldTag} to ${newTag}`))
    } catch (error) {
      console.error(($t ? $t('taskList.errorRenameTag') : 'Error renaming tag') + ':', error)
      throw error
    }
  }

  // ===== 輔助函數 =====

  /**
   * 獲取標籤顏色（如果沒有設定則生成默認顏色）
   * @param {string} tagName - 標籤名稱
   * @returns {string} 顏色代碼
   */
  function getTagColor(tagName) {
    // 如果有設定顏色，使用設定的顏色
    if (tagColors.value[tagName]) {
      return tagColors.value[tagName]
    }

    // 否則根據標籤名稱生成一致的預設顏色
    let hash = 0
    for (let i = 0; i < tagName.length; i++) {
      hash = tagName.charCodeAt(i) + ((hash << 5) - hash)
    }
    const index = Math.abs(hash) % defaultColors.length
    return defaultColors[index]
  }

  /**
   * 根據標籤名稱數組獲取標籤 ID 數組
   * @param {Array} tagNames - 標籤名稱數組
   * @returns {Array} 標籤 ID 數組（使用 tag_id，即 UUID 格式）
   */
  function getTagIds(tagNames) {
    return tagNames.map(tagName => {
      const tagObj = tagsData.value.find(t => t.name === tagName)
      // 優先使用 tag_id（UUID），因為後端 update_order 使用 tag_id 查詢
      return tagObj ? (tagObj.tag_id || tagObj._id) : null
    }).filter(id => id !== null)
  }

  return {
    // 狀態
    tagColors,
    tagsData,
    customTagOrder,

    // 函數
    getAllTags,
    fetchTagColors,
    fetchTagOrder,
    saveTagOrder,
    updateTagColor,
    updateTagColorLocal,
    saveTagColor,
    renameTag,
    deleteTag,
    getTagColor,
    getTagIds,

    // 常量
    presetColors
  }
}
