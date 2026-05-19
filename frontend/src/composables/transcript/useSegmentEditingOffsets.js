import { ref } from 'vue'

/**
 * Canonical DOM ↔ char-offset utilities for the paragraph-mode editor.
 *
 * All consumers (full-text extraction, range building for CSS Custom
 * Highlights, caret-from-point hit-tests) MUST go through these utilities
 * so the char-offset space stays consistent by construction.
 *
 * Char-offset space:
 *  - Excludes U+200B (zero-width space)
 *  - <br>                 → "\n"
 *  - <div> boundary       → "\n" before (if not first content) and after
 *                            (unless the div only contains <br> or the
 *                            running text already ends with "\n")
 *  - .segment-marker / .text-timecode-tooltip elements: skipped entirely
 */

const SKIP_CLASSES = new Set(['segment-marker', 'text-timecode-tooltip'])

function shouldSkip(node) {
  return (
    node.nodeType === Node.ELEMENT_NODE &&
    node.classList &&
    [...node.classList].some((c) => SKIP_CLASSES.has(c))
  )
}

function countCleanLength(raw) {
  let n = 0
  for (let i = 0; i < raw.length; i++) {
    if (raw.charCodeAt(i) !== 0x200b) n++
  }
  return n
}

function liveOffsetForCleanOffset(raw, cleanOffset) {
  let clean = 0
  for (let live = 0; live < raw.length; live++) {
    if (clean === cleanOffset) return live
    if (raw.charCodeAt(live) !== 0x200b) clean++
  }
  return raw.length
}

function cleanOffsetForLiveOffset(raw, liveOffset) {
  const cap = Math.min(liveOffset, raw.length)
  let clean = 0
  for (let live = 0; live < cap; live++) {
    if (raw.charCodeAt(live) !== 0x200b) clean++
  }
  return clean
}

/**
 * Walk all text-contributing nodes under rootEl. Yields:
 *   { kind: 'text', node, charStart, charEnd, rawText }    — real text node
 *   { kind: 'newline', charStart, charEnd }                — synthetic "\n"
 *
 * Synthetic newlines have no DOM offset; consumers that build Ranges only
 * use 'text' entries.
 */
export function* walkTextNodes(rootEl) {
  if (!rootEl) return

  const state = { charIndex: 0, lastWasNewline: true }

  function* visit(node) {
    if (shouldSkip(node)) return

    if (node.nodeType === Node.TEXT_NODE) {
      const raw = node.textContent ?? ''
      const cleanLen = countCleanLength(raw)
      if (cleanLen > 0) {
        yield {
          kind: 'text',
          node,
          charStart: state.charIndex,
          charEnd: state.charIndex + cleanLen,
          rawText: raw,
        }
        state.charIndex += cleanLen
        state.lastWasNewline = raw.endsWith('\n')
      }
      return
    }

    if (node.nodeName === 'BR') {
      yield {
        kind: 'newline',
        charStart: state.charIndex,
        charEnd: state.charIndex + 1,
      }
      state.charIndex += 1
      state.lastWasNewline = true
      return
    }

    if (node.nodeName === 'DIV') {
      if (state.charIndex > 0 && !state.lastWasNewline) {
        yield {
          kind: 'newline',
          charStart: state.charIndex,
          charEnd: state.charIndex + 1,
        }
        state.charIndex += 1
        state.lastWasNewline = true
      }

      const children = Array.from(node.childNodes)
      const hasOnlyBr =
        children.length === 1 && children[0].nodeName === 'BR'

      for (const child of children) {
        yield* visit(child)
      }

      if (children.length > 0 && !hasOnlyBr && !state.lastWasNewline) {
        yield {
          kind: 'newline',
          charStart: state.charIndex,
          charEnd: state.charIndex + 1,
        }
        state.charIndex += 1
        state.lastWasNewline = true
      }
      return
    }

    if (node.nodeType === Node.ELEMENT_NODE) {
      for (const child of Array.from(node.childNodes)) {
        yield* visit(child)
      }
    }
  }

  for (const child of Array.from(rootEl.childNodes)) {
    yield* visit(child)
  }
}

/**
 * Extract the canonical full-text under rootEl.
 */
export function extractText(rootEl) {
  let out = ''
  for (const entry of walkTextNodes(rootEl)) {
    if (entry.kind === 'text') {
      out += entry.rawText.replace(/\u200B/g, '')
    } else {
      out += '\n'
    }
  }
  return out
}

/**
 * Build a flat list of text-node entries for range-building and hit-testing.
 * Synthetic newline entries are excluded — Range endpoints must sit on real
 * text nodes; for char offsets that fall on a synthetic newline we snap to
 * the nearest text node end/start.
 */
export function buildCharIndexMap(rootEl) {
  const entries = []
  for (const entry of walkTextNodes(rootEl)) {
    if (entry.kind === 'text') entries.push(entry)
  }
  return entries
}

function findEndpoint(map, target) {
  if (map.length === 0) return null
  // First text entry whose end covers the target. For targets on a
  // synthetic newline (no real text node there), this snaps to the start
  // of the next text entry, which is what Range endpoints need.
  for (const e of map) {
    if (target <= e.charEnd) {
      const clamped = Math.max(e.charStart, Math.min(target, e.charEnd))
      const liveOffset = liveOffsetForCleanOffset(
        e.rawText,
        clamped - e.charStart
      )
      return { node: e.node, offset: liveOffset }
    }
  }
  const last = map[map.length - 1]
  return { node: last.node, offset: last.rawText.length }
}

/**
 * Build a DOM Range covering [startChar, endChar] in canonical space.
 * Returns null if the map is empty or the range can't be constructed.
 */
export function charOffsetToRange(map, startChar, endChar) {
  if (!map || map.length === 0) return null
  try {
    const startPt = findEndpoint(map, startChar)
    const endPt = findEndpoint(map, endChar)
    if (!startPt || !endPt) return null
    const range = new Range()
    range.setStart(startPt.node, startPt.offset)
    range.setEnd(endPt.node, endPt.offset)
    return range
  } catch {
    return null
  }
}

/**
 * Convert a DOM anchor (node, offset) — typically from
 * caretPositionFromPoint / caretRangeFromPoint — to a canonical char offset.
 * Returns null if the anchor is outside the tracked text.
 */
export function caretToCharOffset(map, node, offset) {
  if (!map || !node) return null
  for (const e of map) {
    if (e.node === node) {
      return e.charStart + cleanOffsetForLiveOffset(e.rawText, offset)
    }
  }
  return null
}

/**
 * Single-region prefix/suffix diff.
 *
 * Returns the minimal change region:
 *   { from, to, newLen }
 *   - from, to: offsets into oldStr (the deleted region is oldStr[from..to])
 *   - newLen:   length of the replacement substring in newStr
 *
 * Returns null when the strings are identical.
 */
export function diffSingleRegion(oldStr, newStr) {
  if (oldStr === newStr) return null

  const oldLen = oldStr.length
  const newLen = newStr.length
  const minLen = Math.min(oldLen, newLen)

  let prefix = 0
  while (prefix < minLen && oldStr[prefix] === newStr[prefix]) prefix++

  let suffix = 0
  while (
    suffix < minLen - prefix &&
    oldStr[oldLen - 1 - suffix] === newStr[newLen - 1 - suffix]
  ) {
    suffix++
  }

  return {
    from: prefix,
    to: oldLen - suffix,
    newLen: newLen - prefix - suffix,
  }
}

/**
 * Apply a single change region [from, to] → newLen to one segment range.
 *
 * Rule (left-bias for pure boundary insertion; otherwise outward gap):
 *   - Segment fully before replacement                → unchanged
 *   - Segment fully after  replacement                → shift by delta
 *   - Segment fully contains replacement              → absorb (ce += delta)
 *   - Segment ends inside replacement (cs < from)     → ce → from (gap right)
 *   - Segment starts inside replacement (ce > to)     → cs → from + newLen
 *                                                       (gap left), ce += delta
 *   - Segment fully inside replacement                → drop (return null)
 *
 * Returns { charStart, charEnd } or null. Other range fields are the caller's
 * responsibility to carry over.
 */
export function applyAnchorRule(cs, ce, from, to, newLen) {
  const delta = newLen - (to - from)

  if (ce < from) return { charStart: cs, charEnd: ce }
  if (cs >= to) return { charStart: cs + delta, charEnd: ce + delta }
  if (cs <= from && to <= ce) return { charStart: cs, charEnd: ce + delta }
  if (cs < from) return { charStart: cs, charEnd: from }
  if (ce > to) return { charStart: from + newLen, charEnd: ce + delta }
  return null
}

/**
 * Editing-session composable. Holds the live segment-offset map plus the
 * input/composition handlers that keep it in sync with a contenteditable.
 *
 * Usage:
 *   const offsets = useSegmentEditingOffsets()
 *   // when entering edit mode, after the editor div is mounted:
 *   offsets.initEditing(divRef, markers)
 *   // bind on the editor:
 *   <div @input="offsets.handleInput($event.currentTarget)"
 *        @compositionstart="offsets.handleCompositionStart()"
 *        @compositionend="offsets.handleCompositionEnd($event.currentTarget)">
 *   // on cancel/save:
 *   offsets.resetEditing()
 *
 *   // read editSegmentRanges / originalTrackedIndices for save & viz.
 */
export function useSegmentEditingOffsets() {
  // [{ segmentIndex, charStart, charEnd, start, end }]
  const editSegmentRanges = ref([])
  const originalTrackedIndices = ref(new Set())
  const snapshot = ref('')
  const isComposing = ref(false)

  function initEditing(rootEl, markers) {
    const list = (markers || []).map((m) => ({
      segmentIndex: m.segmentIndex,
      charStart: m.textStartIndex,
      charEnd: m.textEndIndex,
      start: m.start,
      end: m.end,
    }))
    editSegmentRanges.value = list
    originalTrackedIndices.value = new Set(list.map((r) => r.segmentIndex))
    snapshot.value = rootEl ? extractText(rootEl) : ''
    isComposing.value = false
  }

  function resetEditing() {
    editSegmentRanges.value = []
    originalTrackedIndices.value = new Set()
    snapshot.value = ''
    isComposing.value = false
  }

  function applyDiff(from, to, newLen) {
    const next = []
    for (const r of editSegmentRanges.value) {
      const adjusted = applyAnchorRule(r.charStart, r.charEnd, from, to, newLen)
      if (adjusted && adjusted.charEnd > adjusted.charStart) {
        next.push({
          ...r,
          charStart: adjusted.charStart,
          charEnd: adjusted.charEnd,
        })
      }
      // else: collapsed → drop (Q4 b)
    }
    editSegmentRanges.value = next
  }

  function handleInput(rootEl) {
    if (isComposing.value) return
    if (!rootEl) return
    const newText = extractText(rootEl)
    const diff = diffSingleRegion(snapshot.value, newText)
    if (!diff) return
    applyDiff(diff.from, diff.to, diff.newLen)
    snapshot.value = newText
  }

  function handleCompositionStart() {
    isComposing.value = true
  }

  function handleCompositionEnd(rootEl) {
    isComposing.value = false
    // Absorb the composition's net change in one diff pass.
    handleInput(rootEl)
  }

  /**
   * Extract everything needed to save the current edit:
   *   - fullText: canonical full text from the contenteditable
   *   - updatedSegments: a fresh copy of `segments` with text fields updated
   *     from the current ranges; segments that were tracked at edit start
   *     but have since collapsed/dropped get text = ''
   *   - hasChanges: whether any segment's text differs from the original
   *
   * Untracked segments (short / fuzzy-match failures) are NOT touched.
   *
   * @param {HTMLElement} rootEl - the contenteditable element
   * @param {Array} segments - the original segments array (will be deep-copied)
   * @returns {{ fullText: string, updatedSegments: Array, hasChanges: boolean }}
   */
  function extractForSave(rootEl, segments) {
    const fullText = rootEl ? extractText(rootEl) : ''
    const updatedSegments = (segments || []).map((s) => ({ ...s }))
    let hasChanges = false

    const stillTracked = new Set()
    for (const r of editSegmentRanges.value) {
      if (r.segmentIndex < 0 || r.segmentIndex >= updatedSegments.length) continue
      stillTracked.add(r.segmentIndex)
      const newText = fullText.slice(r.charStart, r.charEnd)
      const oldText = (updatedSegments[r.segmentIndex].text ?? '').trim()
      if (newText.trim() !== oldText) {
        updatedSegments[r.segmentIndex].text = newText
        hasChanges = true
      }
    }

    // 進編輯時有 marker、現在不在 ranges 裡 → 該 segment 被刪光,清空 text
    for (const idx of originalTrackedIndices.value) {
      if (stillTracked.has(idx)) continue
      if (idx < 0 || idx >= updatedSegments.length) continue
      if ((updatedSegments[idx].text ?? '') !== '') {
        updatedSegments[idx].text = ''
        hasChanges = true
      }
    }

    return { fullText, updatedSegments, hasChanges }
  }

  return {
    editSegmentRanges,
    originalTrackedIndices,
    snapshot,
    isComposing,
    initEditing,
    resetEditing,
    handleInput,
    handleCompositionStart,
    handleCompositionEnd,
    extractForSave,
  }
}
