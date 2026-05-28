#!/usr/bin/env bash
#
# build-fonts.sh — 抓 google/fonts 上的 Noto Sans CJK Variable Font，
# 萃取 Regular (wght=400) static instance，寫到 src/utils/pdf/fonts/。
#
# 一次性腳本，更新字體版本時手動跑（不在 CI）。產物 commit 進 repo。
#
# Usage:
#   ./tools/build-fonts.sh                           # 用 google/fonts main HEAD
#   ./tools/build-fonts.sh 69430e34bc2619bbef2a...   # pin 到特定 commit SHA
#
# 依賴：python3 + fonttools (pip install fonttools) + curl

set -euo pipefail

PIN_SHA="${1:-main}"
WORK_DIR=$(mktemp -d)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/src/utils/pdf/fonts"

echo "==> Pin: ${PIN_SHA}"
echo "==> Work: ${WORK_DIR}"
echo "==> Out:  ${OUT_DIR}"

# 解析 SHA（如果 user 給 "main"，撈出實際 commit SHA 寫進 README，避免 main 飄移）
if [ "${PIN_SHA}" = "main" ]; then
    PIN_SHA=$(curl -fsS https://api.github.com/repos/google/fonts/branches/main \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['commit']['sha'])")
    echo "==> Resolved main → ${PIN_SHA}"
fi

mkdir -p "${OUT_DIR}"

# 1. 下載 4 個 variable font
for pair in TC:tc SC:sc JP:jp KR:kr; do
    upper=${pair%:*}
    lower=${pair#*:}
    url="https://raw.githubusercontent.com/google/fonts/${PIN_SHA}/ofl/notosans${lower}/NotoSans${upper}%5Bwght%5D.ttf"
    echo "==> Download NotoSans${upper}[wght].ttf"
    curl -fsSL "$url" -o "${WORK_DIR}/NotoSans${upper}-VF.ttf"
done

# 2. 萃取 Regular instance（wght=400）
for lang in TC SC JP KR; do
    echo "==> Extract Regular from NotoSans${lang}-VF.ttf"
    python3 - <<PY
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
vf = TTFont("${WORK_DIR}/NotoSans${lang}-VF.ttf")
inst = instancer.instantiateVariableFont(vf, {"wght": 400})
inst.save("${OUT_DIR}/NotoSans${lang}-Regular.ttf")
PY
done

# 3. 產生 sha256 checksum
echo "==> Generate sha256.txt"
cd "${OUT_DIR}"
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum NotoSans*-Regular.ttf > sha256.txt
else
    shasum -a 256 NotoSans*-Regular.ttf > sha256.txt
fi

# 4. 清掉暫存
rm -rf "${WORK_DIR}"

echo
echo "✓ Done. Source pin: ${PIN_SHA}"
echo "Files:"
ls -lh "${OUT_DIR}"/NotoSans*-Regular.ttf
echo
echo "記得：（1）更新 fonts/README.md 的 'Pinned commit SHA' 為 ${PIN_SHA}"
echo "      （2）git add + commit + verify production PDF 中文照常 render"
