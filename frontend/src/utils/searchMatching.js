/**
 * Search/replace 的純函數工具。
 *
 * 從 TranscriptDetailView 抽出的 regex 構造與 match enumeration 邏輯。
 * 純運算、無 Vue 依賴、無 DOM 副作用——caller（含 segOffsets / contentVersion
 * 等 DOM-coupled 邏輯）仍留在原處，本檔只負責「規則」。
 *
 * 三處原本散落的 regex 建構模板（escape + 全字邊界 + 大小寫 flags）
 * 在這收成單一 buildSearchRegex。
 */

/**
 * 跳脫正則表達式特殊字元。
 *
 * @param {string} text 原始字串
 * @returns {string} 已 escape 的字串，可安全嵌入 RegExp
 */
export function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 依使用者選項建構搜尋用的 RegExp。
 *
 * @param {string} text 搜尋字串
 * @param {object} options
 * @param {boolean} [options.matchCase=false] 是否區分大小寫
 * @param {boolean} [options.matchWholeWord=false] 是否全字匹配
 * @returns {RegExp|null} 構造失敗（空字串 / 無效 regex）回 null
 */
export function buildSearchRegex(text, { matchCase = false, matchWholeWord = false } = {}) {
  if (!text) return null
  try {
    let pattern = escapeRegExp(text)
    if (matchWholeWord) {
      pattern = `\\b${pattern}\\b`
    }
    const flags = matchCase ? 'g' : 'gi'
    return new RegExp(pattern, flags)
  } catch {
    return null
  }
}

/**
 * 在內容中找出所有匹配位置。
 *
 * @param {string} content 要搜尋的內容
 * @param {RegExp} regex 必須帶 g flag（caller 用 buildSearchRegex 即可）
 * @returns {Array<{ start: number, end: number, text: string }>}
 *   未匹配或 regex 為 null 時回空陣列
 */
export function findAllMatches(content, regex) {
  if (!regex || !content) return []
  const matches = []
  let match
  // 重置 lastIndex 避免共用 regex 時 state pollution
  regex.lastIndex = 0
  while ((match = regex.exec(content)) !== null) {
    matches.push({
      start: match.index,
      end: match.index + match[0].length,
      text: match[0],
    })
    // 防呆：若 regex 匹配空字串會無限迴圈
    if (match.index === regex.lastIndex) {
      regex.lastIndex++
    }
  }
  return matches
}
