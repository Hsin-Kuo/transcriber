# Background Images

## 使用說明

將你的背景照片放在此資料夾中。

### 建議規格

- **格式**：JPG, PNG, WebP
- **尺寸**：1920x1080 或更高（支援 4K）
- **檔案大小**：建議壓縮至 500KB 以下（優化載入速度）
- **色調**：淺色系照片（天空、白牆、明亮場景）

### 範例檔名

- `background.jpg` - 主背景
- `background-light.jpg` - 淺色版本
- `background-pattern.png` - 圖案/紋理

### 訪問路徑

在程式碼中使用：
```css
background-image: url('/images/background.jpg');
```

或在 Vue 組件中：
```vue
<div :style="{ backgroundImage: 'url(/images/background.jpg)' }">
```
