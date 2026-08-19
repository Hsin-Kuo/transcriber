#!/usr/bin/env bash
# XSS 回歸掃描（docs/XSS_AUDIT_TODO.md TODO-11）
#
# 守住 2026-07-05 盤點確立的「全站零 HTML sink」基線：
#   - 前端零 v-html / innerHTML 注入 / eval
#   - 後端零 HTML 輸出 endpoint
# 任何非預期命中即 exit 1。CI（.github/workflows/test.yml）每個 PR 都會跑。
#
# 要新增例外（allowlist）前必讀 docs/XSS_AUDIT_TODO.md：
#   - 純註解行自動放行（註解不會被執行/渲染）
#   - 其餘例外必須是「非使用者可控」或「輸出端已逃逸」，且逐條寫明理由
#   - 若要引入 v-html，必須同時引入 DOMPurify 並過 security review
set -uo pipefail

cd "$(dirname "$0")/.."

fail=0

# 放行：純註解行（// * <!-- #）＋ 逐條列名的已審例外
allowlist_filter() {
  grep -vE '^[^:]+:[0-9]+:[[:space:]]*(//|\*|<!--|#)' |
    # GoogleSignInButton：innerHTML = '' 只用來清空節點，無注入（audit §0）
    grep -vE "GoogleSignInButton\.vue:[0-9]+:.*innerHTML = ''[[:space:]]*$" ||
    true
}

check() {
  local label="$1" pattern="$2"
  shift 2
  local hits
  hits=$(grep -rnE "$pattern" "$@" 2>/dev/null | allowlist_filter)
  if [ -n "$hits" ]; then
    echo "✗ ${label}：非預期命中——新增 HTML sink 前先讀 docs/XSS_AUDIT_TODO.md"
    echo "$hits"
    fail=1
  else
    echo "✓ ${label}"
  fi
}

check "前端 v-html（預期 0）" \
  'v-html' frontend/src admin-frontend/src

check "前端 DOM sink（innerHTML/outerHTML/insertAdjacentHTML/document.write）" \
  'innerHTML|outerHTML|insertAdjacentHTML|document\.write' frontend/src admin-frontend/src

check "前端 eval / new Function（預期 0）" \
  '\beval\(|new Function' frontend/src admin-frontend/src

check "後端 HTML 輸出（HTMLResponse/text\\/html/Jinja2，預期 0）" \
  'HTMLResponse|text/html|Jinja2|TemplateResponse' src/

exit "$fail"
