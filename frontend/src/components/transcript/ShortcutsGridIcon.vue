<!--
  ShortcutsGridIcon — 播放區「音檔快捷鍵」的 4×3 點狀 glyph。

  playback 觸發鈕（KeyboardShortcutsInfo）與 header tip（audioShortcuts）
  共用同一份，確保 tip 文案指到的圖示與畫面上那顆一致（避免各抄一份 drift）。
  單一 root <svg>，class / width 等屬性由 caller fall-through；fill 走 currentColor。
-->
<template>
  <svg viewBox="0 0 48 36" fill="currentColor" aria-hidden="true">
    <circle cx="9" cy="8" r="2.5" fill="currentColor" />
    <circle cx="19" cy="8" r="2.5" fill="currentColor" />
    <circle cx="29" cy="8" r="2.5" fill="currentColor" />
    <circle cx="39" cy="8" r="2" fill="none" stroke="currentColor" stroke-width="1" />
    <circle cx="9" cy="18" r="2" fill="none" stroke="currentColor" stroke-width="1" />
    <circle cx="19" cy="18" r="2" fill="none" stroke="currentColor" stroke-width="1" />
    <circle cx="29" cy="18" r="2" fill="none" stroke="currentColor" stroke-width="1" />
    <circle cx="39" cy="18" r="2.5" fill="currentColor" />
    <circle cx="9" cy="28" r="2" fill="none" stroke="currentColor" stroke-width="1" />
    <circle cx="19" cy="28" r="2" fill="none" stroke="currentColor" stroke-width="1" />
    <circle cx="29" cy="28" r="2" fill="none" stroke="currentColor" stroke-width="1" />
    <circle cx="39" cy="28" r="2.5" fill="currentColor" />
  </svg>
</template>
