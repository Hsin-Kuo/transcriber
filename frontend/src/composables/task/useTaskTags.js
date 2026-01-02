import { ref, computed } from 'vue'
import api from '../../utils/api'

// 預設顏色選項（與 TaskList.vue 中保持一致）
export const presetColors = [
  '#667eea', '#f093fb', '#4facfe', '#43e97b', '#fa709a',
  '#feca57', '#48dbfb', '#ff6b6b', '#ee5a6f', '#c44569',
  '#a29bfe', '#fd79a8', '#fdcb6e', '#00b894', '#0984e3',
  '#6c5ce7', '#e17055', '#74b9ff', '#55efc4', '#ffeaa7'
]

// 默認顏色（用於生成 hash）
const defaultColors = [
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
    } catch (error) {
      console.error(($t ? $t('taskList.errorFetchTagColors') : 'Error fetching tag colors') + ':', error)
    }
  }

  /**
   * 從後端獲取標籤順序
   */
  async function fetchTagOrder() {
    try {
      const response = await api.get('/tags/order')
      if (response.data.order && response.data.order.length > 0) {
        customTagOrder.value = response.data.order
        console.log('✅ ' + ($t ? $t('taskList.logLoadedTagOrder') : 'Loaded custom tag order'), response.data.count, ($t ? $t('taskList.logTagCount') : 'tags'))
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
   * 更新標籤顏色
   * @param {string} tagName - 標籤名稱
   * @param {string} color - 顏色代碼
   */
  async function updateTagColor(tagName, color) {
    try {
      // 從 tagsData 中找到對應的標籤對象
      const tagObj = tagsData.value.find(t => t.name === tagName)
      if (!tagObj) {
        throw new Error($t ? $t('taskList.errorTagNotFound') : 'Tag not found')
      }

      // 使用正確的 API 端點和標籤 ID
      await api.put(`/tags/${tagObj._id || tagObj.tag_id}`, {
        name: tagObj.name,
        color: color,
        description: tagObj.description || null
      })

      // 更新本地顏色
      tagColors.value[tagName] = color
    } catch (error) {
      console.error(($t ? $t('taskList.errorUpdateTagColor') : 'Error updating tag color') + ':', error)
      throw error
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
   * @returns {Array} 標籤 ID 數組
   */
  function getTagIds(tagNames) {
    return tagNames.map(tagName => {
      const tagObj = tagsData.value.find(t => t.name === tagName)
      return tagObj ? (tagObj._id || tagObj.tag_id) : null
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
    renameTag,
    getTagColor,
    getTagIds,

    // 常量
    presetColors
  }
}
