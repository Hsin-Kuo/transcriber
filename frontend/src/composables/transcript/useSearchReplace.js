import { ref, nextTick, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { buildSearchRegex, findAllMatches } from '../../utils/searchMatching'
import {
  applyAnchorRule,
  buildCharIndexMap,
  charOffsetToRange,
  extractText,
} from './useSegmentEditingOffsets'

/**
 * 搜尋/取代 composable
 *
 * 封裝整個 search/replace 生命週期：狀態、搜尋邏輯、CSS Highlight API、
 * 取代（含 segment offset 同步）、以及非編輯模式的 highlight 渲染 helper。
 */
export function useSearchReplace({
  textareaRef,
  currentTranscript,
  displayMode,
  isEditing,
  segments,
  groupedSegments,
  segmentMarkers,
  generateSegmentMarkers,
  segOffsets,
}) {
  const { t } = useI18n()

  // ========== State ==========
  const searchText = ref('')
  const replaceText = ref('')
  const searchMatches = ref([])
  const currentMatchIndex = ref(0)
  const matchCase = ref(false)
  const matchWholeWord = ref(false)
  const isReplacing = ref(false)
  const contentVersion = ref(0)

  // ========== Lifecycle ==========
  let isMounted = true
  const scrollRestoreTimers = []

  onUnmounted(() => {
    isMounted = false
    scrollRestoreTimers.forEach(id => clearTimeout(id))
  })

  // isReplacing false→true→false cycle: 重新掛載 contenteditable 後需要重新 init segOffsets
  watch(isReplacing, (newVal, oldVal) => {
    if (oldVal === true && newVal === false && isEditing.value && displayMode.value === 'paragraph') {
      nextTick(() => {
        if (textareaRef.value) {
          segOffsets.initEditing(textareaRef.value, segmentMarkers.value)
        }
      })
    }
  })

  // ========== 搜尋 ==========

  function handleSearch(text) {
    const wasSearching = searchText.value && searchMatches.value.length > 0
    searchText.value = text

    if (!text) {
      if (CSS.highlights) {
        CSS.highlights.delete('search-highlight')
        CSS.highlights.delete('search-highlight-current')
      }
      if (isEditing.value && wasSearching) {
        nextTick(() => {
          searchMatches.value = []
          currentMatchIndex.value = 0
        })
      } else {
        searchMatches.value = []
        currentMatchIndex.value = 0
      }
      return
    }

    const content = getSearchableContent()
    const regex = buildSearchRegex(text, {
      matchCase: matchCase.value,
      matchWholeWord: matchWholeWord.value,
    })
    const matches = findAllMatches(content, regex)

    searchMatches.value = matches
    currentMatchIndex.value = matches.length > 0 ? 0 : 0

    // paragraph 模式（編輯/非編輯）皆走 CSS Highlight API
    if (displayMode.value === 'paragraph') {
      nextTick(() => {
        applySearchHighlightsWithCSS()
      })
    }

    if (matches.length > 0) {
      scrollToMatch(0)
    }
  }

  function getSearchableContent() {
    if (displayMode.value === 'paragraph') {
      if (textareaRef.value) {
        return extractText(textareaRef.value)
      }
      return currentTranscript.value.content || ''
    } else if (displayMode.value === 'subtitle') {
      let content = ''
      groupedSegments.value.forEach(group => {
        group.segments.forEach(segment => {
          content += segment.text + '\n'
        })
      })
      return content
    }
    return ''
  }

  // ========== CSS Highlight API（編輯模式） ==========

  function applySearchHighlightsWithCSS() {
    if (!CSS.highlights) return

    CSS.highlights.delete('search-highlight')
    CSS.highlights.delete('search-highlight-current')

    if (!textareaRef.value || searchMatches.value.length === 0) return

    const map = buildCharIndexMap(textareaRef.value)
    const ranges = []
    const currentRanges = []

    searchMatches.value.forEach((match, matchIndex) => {
      const range = charOffsetToRange(map, match.start, match.end)
      if (!range) return
      if (matchIndex === currentMatchIndex.value) {
        currentRanges.push(range)
      } else {
        ranges.push(range)
      }
    })

    if (ranges.length > 0) {
      CSS.highlights.set('search-highlight', new Highlight(...ranges))
    }
    if (currentRanges.length > 0) {
      CSS.highlights.set('search-highlight-current', new Highlight(...currentRanges))
    }
  }

  // ========== 導航 ==========

  function goToPreviousMatch() {
    if (searchMatches.value.length === 0) return
    currentMatchIndex.value = (currentMatchIndex.value - 1 + searchMatches.value.length) % searchMatches.value.length
    if (displayMode.value === 'paragraph') {
      applySearchHighlightsWithCSS()
    }
    scrollToMatch(currentMatchIndex.value)
  }

  function goToNextMatch() {
    if (searchMatches.value.length === 0) return
    currentMatchIndex.value = (currentMatchIndex.value + 1) % searchMatches.value.length
    if (displayMode.value === 'paragraph') {
      applySearchHighlightsWithCSS()
    }
    scrollToMatch(currentMatchIndex.value)
  }

  function scrollToMatch(index) {
    if (displayMode.value === 'paragraph') {
      // paragraph 模式（編輯/非編輯）統一用 range 幾何捲動（無 .search-highlight DOM 可用）
      nextTick(() => {
        if (textareaRef.value && searchMatches.value[index]) {
          const match = searchMatches.value[index]
          const range = findRangeForMatch(match)
          if (range) {
            const rect = range.getBoundingClientRect()
            const containerRect = textareaRef.value.getBoundingClientRect()
            const scrollTop = textareaRef.value.scrollTop + rect.top - containerRect.top - containerRect.height / 2
            textareaRef.value.scrollTo({ top: scrollTop, behavior: 'smooth' })
          }
        }
      })
    } else if (displayMode.value === 'subtitle') {
      nextTick(() => {
        const highlightedElements = document.querySelectorAll('.search-highlight')
        if (highlightedElements[index]) {
          highlightedElements[index].scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
      })
    }
  }

  function findRangeForMatch(match) {
    if (!textareaRef.value) return null

    const textNodes = []
    let charIndex = 0
    let lastCharWasNewline = false

    function collectTextNodes(node) {
      if (node.classList && (node.classList.contains('segment-marker') || node.classList.contains('text-timecode-tooltip') || node.classList.contains('timecode-marker-overlay'))) {
        return
      }
      if (node.nodeType === Node.TEXT_NODE) {
        const text = node.textContent || ''
        if (text.length > 0) {
          const cleanText = text.replace(/​/g, '')
          if (cleanText.length > 0) {
            textNodes.push({ node, start: charIndex, end: charIndex + cleanText.length })
            charIndex += cleanText.length
            lastCharWasNewline = cleanText.endsWith('\n')
          }
        }
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (node.nodeName === 'BR') {
          charIndex += 1
          lastCharWasNewline = true
          return
        }
        if (node.nodeName === 'DIV' && charIndex > 0 && !lastCharWasNewline) {
          charIndex += 1
          lastCharWasNewline = true
        }
        for (const child of node.childNodes) {
          collectTextNodes(child)
        }
        if (node.nodeName === 'DIV' && node.childNodes.length > 0) {
          const hasOnlyBr = node.childNodes.length === 1 && node.childNodes[0].nodeName === 'BR'
          if (!hasOnlyBr && !lastCharWasNewline) {
            charIndex += 1
            lastCharWasNewline = true
          }
        }
      }
    }

    for (const child of textareaRef.value.childNodes) {
      collectTextNodes(child)
    }

    for (const textNode of textNodes) {
      if (match.start >= textNode.start && match.start < textNode.end) {
        try {
          const range = new Range()
          const startOffset = match.start - textNode.start
          const endOffset = Math.min(textNode.node.textContent.length, match.end - textNode.start)
          range.setStart(textNode.node, startOffset)
          range.setEnd(textNode.node, endOffset)
          return range
        } catch (e) {
          return null
        }
      }
    }
    return null
  }

  // ========== 取代 ==========

  function handleReplaceCurrent(newReplaceText) {
    if (!isEditing.value || searchMatches.value.length === 0) return

    replaceText.value = newReplaceText
    const match = searchMatches.value[currentMatchIndex.value]

    if (displayMode.value === 'paragraph') {
      let content = currentTranscript.value.content || ''
      if (textareaRef.value) {
        content = extractText(textareaRef.value)
      }

      const before = content.substring(0, match.start)
      const after = content.substring(match.end)
      const replacedContent = before + newReplaceText + after

      const from = match.start
      const to = match.end
      const newLen = newReplaceText.length
      segments.value = segments.value.map((seg, idx) => {
        const range = segOffsets.editSegmentRanges.value.find(
          (r) => r.segmentIndex === idx
        )
        if (!range) return seg
        const adjusted = applyAnchorRule(
          range.charStart,
          range.charEnd,
          from,
          to,
          newLen
        )
        if (!adjusted || adjusted.charEnd <= adjusted.charStart) {
          return { ...seg, text: newReplaceText }
        }
        return { ...seg, text: replacedContent.slice(adjusted.charStart, adjusted.charEnd) }
      })

      updateContentAfterReplace(replacedContent)

      const previousIndex = currentMatchIndex.value
      nextTick(() => {
        nextTick(() => {
          nextTick(() => {
            handleSearch(searchText.value)
            if (searchMatches.value.length > 0) {
              const nextIndex = Math.min(previousIndex, searchMatches.value.length - 1)
              currentMatchIndex.value = nextIndex
              if (isEditing.value && displayMode.value === 'paragraph') {
                applySearchHighlightsWithCSS()
              }
              scrollToMatch(nextIndex)
            }
          })
        })
      })
    } else if (displayMode.value === 'subtitle') {
      let charCount = 0
      let found = false

      for (const group of groupedSegments.value) {
        if (found) break
        for (const segment of group.segments) {
          const segmentEnd = charCount + segment.text.length + 1
          if (match.start >= charCount && match.start < segmentEnd) {
            const localStart = match.start - charCount
            const localEnd = match.end - charCount
            segment.text = segment.text.substring(0, localStart) + newReplaceText + segment.text.substring(localEnd)
            found = true
            break
          }
          charCount = segmentEnd
        }
      }

      const previousIndex = currentMatchIndex.value
      nextTick(() => {
        handleSearch(searchText.value)
        if (searchMatches.value.length > 0) {
          const nextIndex = Math.min(previousIndex, searchMatches.value.length - 1)
          currentMatchIndex.value = nextIndex
          scrollToMatch(nextIndex)
        }
      })
    }
  }

  function handleReplaceAllNew(newReplaceText) {
    if (!isEditing.value || searchMatches.value.length === 0) return

    replaceText.value = newReplaceText
    const searchPattern = searchText.value

    const confirmMessage = t('searchReplace.confirmReplaceAll', {
      count: searchMatches.value.length,
      search: searchPattern,
      replace: newReplaceText
    })
    if (!confirm(confirmMessage)) {
      return
    }

    if (displayMode.value === 'paragraph') {
      let content = currentTranscript.value.content || ''
      if (textareaRef.value) {
        content = extractText(textareaRef.value)
      }

      const regex = buildSearchRegex(searchPattern, {
        matchCase: matchCase.value,
        matchWholeWord: matchWholeWord.value,
      })
      const replacedContent = content.replace(regex, newReplaceText)

      segments.value = segments.value.map((seg, idx) => {
        const range = segOffsets.editSegmentRanges.value.find(
          (r) => r.segmentIndex === idx
        )
        if (!range) return seg
        const currentText = content.slice(range.charStart, range.charEnd)
        return { ...seg, text: currentText.replace(regex, newReplaceText) }
      })

      updateContentAfterReplace(replacedContent)

      searchMatches.value = []
      currentMatchIndex.value = 0
    } else if (displayMode.value === 'subtitle') {
      const regex = buildSearchRegex(searchPattern, {
        matchCase: matchCase.value,
        matchWholeWord: matchWholeWord.value,
      })

      groupedSegments.value.forEach(group => {
        group.segments.forEach(segment => {
          segment.text = segment.text.replace(regex, newReplaceText)
        })
      })

      searchMatches.value = []
      currentMatchIndex.value = 0
    }
  }

  function updateContentAfterReplace(replacedContent) {
    let savedScrollTop = 0
    if (textareaRef.value) {
      savedScrollTop = textareaRef.value.scrollTop
    }

    isReplacing.value = true
    segmentMarkers.value = []
    currentTranscript.value.content = replacedContent
    contentVersion.value++

    if (segments.value && currentTranscript.value.content) {
      generateSegmentMarkers(segments.value, currentTranscript.value.content)
    }

    const timerId = setTimeout(() => {
      if (!isMounted) return
      isReplacing.value = false

      nextTick(() => {
        if (!isMounted) return
        if (savedScrollTop > 0 && textareaRef.value) {
          textareaRef.value.scrollTop = savedScrollTop
        }
      })
    }, 50)
    scrollRestoreTimers.push(timerId)
  }

  // ========== 渲染 Helper（非編輯模式 highlight） ==========

  function getContentParts() {
    const content = currentTranscript.value.content || ''

    if (!segmentMarkers.value || segmentMarkers.value.length === 0) {
      return [{ text: content, isMarker: false }]
    }

    const parts = []
    let lastIndex = 0

    const sortedMarkers = [...segmentMarkers.value].sort((a, b) => a.textStartIndex - b.textStartIndex)

    sortedMarkers.forEach(marker => {
      if (marker.textStartIndex > lastIndex) {
        parts.push({
          text: content.substring(lastIndex, marker.textStartIndex),
          isMarker: false
        })
      }

      parts.push({
        text: marker.text,
        isMarker: true,
        start: marker.start,
        end: marker.end,
        segmentIndex: marker.segmentIndex
      })

      lastIndex = marker.textEndIndex
    })

    if (lastIndex < content.length) {
      parts.push({
        text: content.substring(lastIndex),
        isMarker: false
      })
    }

    return parts
  }

  function getContentPartsWithHighlight() {
    const parts = getContentParts()

    if (isEditing.value || !searchText.value || searchMatches.value.length === 0) {
      return parts
    }

    const result = []
    let globalCharIndex = 0

    for (const part of parts) {
      if (!part.isMarker) {
        const subParts = splitTextWithHighlightByPosition(part.text, globalCharIndex)
        result.push(...subParts)
        globalCharIndex += part.text.length
      } else {
        result.push(part)
        globalCharIndex += part.text.length
      }
    }

    return result
  }

  function splitTextWithHighlightByPosition(text, startPosition) {
    if (!searchText.value || searchMatches.value.length === 0) {
      return [{ text, isMarker: false, isHighlight: false }]
    }

    const endPosition = startPosition + text.length
    const parts = []
    let lastIndex = 0

    const relevantMatches = searchMatches.value
      .map((match, idx) => ({ ...match, matchIndex: idx }))
      .filter(match => match.start < endPosition && match.end > startPosition)

    for (const match of relevantMatches) {
      const localStart = Math.max(0, match.start - startPosition)
      const localEnd = Math.min(text.length, match.end - startPosition)

      if (localStart > lastIndex) {
        parts.push({
          text: text.substring(lastIndex, localStart),
          isMarker: false,
          isHighlight: false
        })
      }

      parts.push({
        text: text.substring(localStart, localEnd),
        isMarker: false,
        isHighlight: true,
        isCurrent: match.matchIndex === currentMatchIndex.value
      })

      lastIndex = localEnd
    }

    if (lastIndex < text.length) {
      parts.push({
        text: text.substring(lastIndex),
        isMarker: false,
        isHighlight: false
      })
    }

    if (parts.length === 0) {
      return [{ text, isMarker: false, isHighlight: false }]
    }

    return parts
  }

  function splitTextWithHighlight(text, segmentIndex) {
    if (!searchText.value || !text) {
      return [{ text, isHighlight: false }]
    }

    const parts = []
    let lastIndex = 0

    const regex = buildSearchRegex(searchText.value, {
      matchCase: matchCase.value,
      matchWholeWord: matchWholeWord.value,
    })
    if (!regex) return [{ text, isHighlight: false }]

    try {
      let match

      let globalOffset = 0
      const sortedMarkers = [...segmentMarkers.value].sort((a, b) => a.textStartIndex - b.textStartIndex)
      const marker = sortedMarkers.find(m => m.segmentIndex === segmentIndex)
      if (marker) {
        globalOffset = marker.textStartIndex
      }

      while ((match = regex.exec(text)) !== null) {
        if (match.index > lastIndex) {
          parts.push({
            text: text.substring(lastIndex, match.index),
            isHighlight: false
          })
        }

        const globalMatchStart = globalOffset + match.index
        const isCurrent = searchMatches.value.some((m, idx) =>
          m.start === globalMatchStart && idx === currentMatchIndex.value
        )

        parts.push({
          text: match[0],
          isHighlight: true,
          isCurrent
        })

        lastIndex = match.index + match[0].length
      }
    } catch (e) {
      return [{ text, isHighlight: false }]
    }

    if (lastIndex < text.length) {
      parts.push({
        text: text.substring(lastIndex),
        isHighlight: false
      })
    }

    if (parts.length === 0) {
      return [{ text, isHighlight: false }]
    }

    return parts
  }

  // ========== 外部整合 helper ==========

  function clearHighlights() {
    if (CSS.highlights) {
      CSS.highlights.delete('search-highlight')
      CSS.highlights.delete('search-highlight-current')
    }
  }

  function reSearch() {
    if (searchText.value) {
      nextTick(() => {
        handleSearch(searchText.value)
      })
    }
  }

  function reapplyHighlightsIfNeeded() {
    if (displayMode.value === 'paragraph' && searchMatches.value.length > 0) {
      nextTick(() => {
        applySearchHighlightsWithCSS()
      })
    }
  }

  return {
    // State
    searchText,
    replaceText,
    searchMatches,
    currentMatchIndex,
    matchCase,
    matchWholeWord,
    isReplacing,
    contentVersion,

    // Search
    handleSearch,
    getSearchableContent,

    // Navigation
    goToPreviousMatch,
    goToNextMatch,
    scrollToMatch,

    // Replace
    handleReplaceCurrent,
    handleReplaceAllNew,

    // Rendering
    getContentPartsWithHighlight,
    splitTextWithHighlight,

    // Integration helpers
    clearHighlights,
    reSearch,
    reapplyHighlightsIfNeeded,
    applySearchHighlightsWithCSS,
  }
}
