import { ref, computed } from 'vue'
import api from '../../utils/api'

/**
 * 預設顏色選項
 * 標籤調色盤（quick-select 與 hash 自動配色共用同一組，順序需一致）
 * 保持為 hex 值是因為需要存儲到數據庫和動態設置樣式
 */
export const presetColors = [
  '#fa709a', '#ffa69e', '#feca57', '#86bbd8', '#9cbb7c',
  '#1f7a8c', '#606d5d', '#8c7051', '#cd8987', '#c44569'
]

/**
 * 默認顏色（用於根據標籤名稱 hash 生成顏色）
 * 對應 colors.css 中的標籤預設色
 */
const defaultColors = [
  '#fa709a', // 粉紅 --tag-color-1
  '#ffa69e', // 珊瑚粉 --tag-color-2
  '#feca57', // 橘黃 --tag-color-3
  '#86bbd8', // 霧藍 --tag-color-4
  '#9cbb7c', // 橄欖綠 --tag-color-5
  '#1f7a8c', // 深青 --tag-color-6
  '#606d5d', // 灰綠 --tag-color-7
  '#8c7051', // 棕褐 --tag-color-8
  '#cd8987', // 玫瑰褐 --tag-color-9
  '#c44569', // 桃紅 --tag-color-10
]

// ===== 全局共享狀態 =====
// 這些 ref 在所有組件間共享，確保標籤顏色一致性
const globalTagColors = ref({})
const globalTagsData = ref([]) // 存儲完整的標籤信息（包含 ID）
const globalCustomTagOrder = ref([])

// 並發 fetch dedupe：多個 component 同時掛載時共享同一個 in-flight request
let inflightFetchTags = null

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
   * 從後端獲取全部標籤（含 id / color / order），寫入共享狀態
   *
   * 並發呼叫會共享同一個 in-flight request，避免多個 component 同時 mount
   * 時對 GET /tags 重複請求。Mutation 後（rename / reorder / color）想強制
   * 重抓時，等前一個 request 結束後再 call 即可拿到新資料。
   */
  async function fetchTagColors() {
    if (inflightFetchTags) return inflightFetchTags

    inflightFetchTags = (async () => {
      try {
        const response = await api.get('/tags')
        const tags = response.data || []

        tagsData.value = tags

        const colors = {}
        tags.forEach(tag => {
          if (tag.color) colors[tag.name] = tag.color
        })
        tagColors.value = colors

        // tags 已按 order 欄位排序
        if (tags.length > 0) {
          customTagOrder.value = tags.map(tag => tag.name)
        }
      } catch (error) {
        console.error(($t ? $t('taskList.errorFetchTagColors') : 'Error fetching tag colors') + ':', error)
      } finally {
        inflightFetchTags = null
      }
    })()

    return inflightFetchTags
  }

  /**
   * @deprecated 保留給舊呼叫端；資料與 fetchTagColors 完全相同。
   */
  const fetchTagOrder = fetchTagColors

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
   * 重命名標籤（atomic：透過後端 PUT /tags/{id}）
   *
   * 後端 update_tag 會原子處理：
   * 1) 驗證新名稱在同 user 唯一
   * 2) update_many + arrayFilters 一次改完所有 task 的 tags 陣列
   * 3) tags collection 的 record name 直接 update（tag_id / color / order 不變）
   *
   * @param {string} oldTag - 舊標籤名稱
   * @param {string} newTag - 新標籤名稱
   * @param {Array} _tasks - 任務列表（保留參數以維持呼叫端相容，不再使用）
   */
  async function renameTag(oldTag, newTag, _tasks) {
    try {
      // 找出 tag 物件
      let tagObj = tagsData.value.find(t => t.name === oldTag)

      // 若本地 tagsData 沒有（純從 task.tags 推導出來的孤兒 tag），
      // 先 fetch 一次：後端 get_all_tags 會自動補建缺少的 tag record
      if (!tagObj) {
        await fetchTagColors()
        tagObj = tagsData.value.find(t => t.name === oldTag)
      }

      if (!tagObj) {
        throw new Error(`找不到標籤「${oldTag}」`)
      }

      const tagId = tagObj.tag_id || tagObj._id

      // 單一原子呼叫：rename + cascade 改所有 task
      await api.put(`/tags/${tagId}`, {
        name: newTag,
        color: tagObj.color || null,
        description: tagObj.description || null
      })

      // 本地狀態同步（避免 UI 短暫顯示舊名；之後 parent 會 fetchTagColors 再對齊）
      if (customTagOrder.value.includes(oldTag)) {
        const index = customTagOrder.value.indexOf(oldTag)
        customTagOrder.value[index] = newTag
      }
      if (tagColors.value[oldTag]) {
        const next = { ...tagColors.value, [newTag]: tagColors.value[oldTag] }
        delete next[oldTag]
        tagColors.value = next
      }
      const idx = tagsData.value.findIndex(t => t.name === oldTag)
      if (idx !== -1) {
        tagsData.value = tagsData.value.map((t, i) =>
          i === idx ? { ...t, name: newTag } : t
        )
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
