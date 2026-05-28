# Backend PDF Fonts — Noto Sans CJK

ReportLab 渲染 PDF 時用的字體，4 個語言各一個 Regular weight static TTF。

| 檔案 | 語言 | 大小 |
|---|---|---|
| NotoSansTC-Regular.ttf | 繁體中文（含 CNS11643）| 6.8 MB |
| NotoSansSC-Regular.ttf | 簡體中文（含 GB18030）| 10 MB |
| NotoSansJP-Regular.ttf | 日文（JIS X 0208 + kana）| 5.5 MB |
| NotoSansKR-Regular.ttf | 韓文（Hangul + Hanja）| 5.9 MB |
| **合計** | | **~28 MB** |

## 來源

- 上游 repo：[`google/fonts`](https://github.com/google/fonts) `ofl/notosans{tc,sc,jp,kr}/`
- Pinned commit SHA：`69430e34bc2619bbef2a6944bb42ec461b900d43`（2026-05-27）
- 上游檔案是 **variable font**（含所有 weight 100-900）。我們用 fontTools 的
  `varLib.instancer` 萃取 `wght=400`（Regular）static instance，把檔案壓小
  ~40%（47MB → 28MB），**glyph 覆蓋率不變**。

## 為何不用 subset 版

使用者要求逐字稿不能缺字（罕用字、人名、地名）。subset 雖然能壓到 ~6MB，
但漏字風險不可接受。Full glyph + 單一 weight 是兼顧大小與覆蓋的平衡。

## 如何更新

需要重新抓字體時跑 `tools/build-fonts.sh`：
```bash
./tools/build-fonts.sh                          # 抓最新 google/fonts main
./tools/build-fonts.sh 69430e34bc...            # 抓特定 commit SHA
```
跑完會：
1. 抓 4 個 variable font 到 /tmp
2. 萃取 wght=400 instance
3. 覆寫 src/utils/pdf/fonts/NotoSans*-Regular.ttf
4. 更新 sha256.txt

修改後 commit 並 verify sha256（CI 啟動時會 check，防止字體 corruption）。

## License

Noto Sans 採用 **SIL Open Font License 1.1**（OFL）。
完整授權見 [google/fonts LICENSE](https://github.com/google/fonts/blob/main/ofl/notosanstc/OFL.txt)。
此 license 允許再散布、商用、修改，唯一限制是不可單獨銷售字體本身。
