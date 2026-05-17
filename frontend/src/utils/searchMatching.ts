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

export interface SearchOptions {
  matchCase?: boolean
  matchWholeWord?: boolean
}

export interface SearchMatch {
  start: number
  end: number
  text: string
}

/**
 * 跳脫正則表達式特殊字元。
 */
export function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 依使用者選項建構搜尋用的 RegExp。
 *
 * @returns 構造失敗（空字串 / 無效 regex）回 null
 */
export function buildSearchRegex(
  text: string,
  { matchCase = false, matchWholeWord = false }: SearchOptions = {},
): RegExp | null {
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
 * @param regex 必須帶 g flag（caller 用 buildSearchRegex 即可）
 * @returns 未匹配或 regex 為 null 時回空陣列
 */
export function findAllMatches(content: string, regex: RegExp | null): SearchMatch[] {
  if (!regex || !content) return []
  const matches: SearchMatch[] = []
  let match: RegExpExecArray | null
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
