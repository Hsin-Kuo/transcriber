/**
 * Contenteditable 輸入事件處理 Composable
 *
 * 職責：
 * - 貼上事件（強制純文字）
 * - IME composition 守衛（Safari compositionend 時序問題）
 * - Enter 攔截（插入 \n text node 保持 DOM flat）
 * - Alt+Arrow 播放速度快捷鍵（編輯區內）
 */
export function useContentEditableInput({ segOffsets, playbackRate, setPlaybackRate }) {
  let compositionJustEnded = false

  function handlePaste(e) {
    e.preventDefault()
    const text = e.clipboardData?.getData('text/plain') || ''
    if (text) {
      document.execCommand('insertText', false, text)
    }
  }

  function handleCompositionEnd(e) {
    compositionJustEnded = true
    segOffsets.handleCompositionEnd(e.currentTarget)
    setTimeout(() => { compositionJustEnded = false }, 0)
  }

  function handleContentEditableKeyDown(e) {
    if (e.key === 'Enter' && !e.isComposing && !compositionJustEnded) {
      e.preventDefault()
      const sel = window.getSelection()
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0)
        range.deleteContents()
        const nl = document.createTextNode('\n')
        range.insertNode(nl)
        range.setStartAfter(nl)
        range.setEndAfter(nl)
        sel.removeAllRanges()
        sel.addRange(range)
        segOffsets.handleInput(e.currentTarget)
      }
      return
    }

    if (!e.altKey) return

    if (e.key === 'ArrowUp') {
      e.preventDefault()
      e.stopPropagation()
      const newRate = Math.min(2, playbackRate.value + 0.25)
      setPlaybackRate(newRate)
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      e.stopPropagation()
      const newRate = Math.max(0.25, playbackRate.value - 0.25)
      setPlaybackRate(newRate)
      return
    }
  }

  return {
    handlePaste,
    handleCompositionEnd,
    handleContentEditableKeyDown,
  }
}
