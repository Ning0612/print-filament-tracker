# 材料帳本 Filament Ledger — UI 設計規範

版本：`1.1`  
名稱：`Filament Ledger／材料帳本`  
適用範圍：`web/templates/`、`web/static/style.css`、`web/translations/`

## 1. 設計定位

材料帳本 Filament Ledger 是本機使用的 3D 列印材料資產工具。WebUI 的主角是「材料的狀態、消耗與可追溯性」，不是列印機控制介面。

採用「編輯型工業工作室」語言：安靜、精準、可掃讀，像一本持續更新的材料帳本。**帳本語言集中在資料本身（表格規線、出入帳色語、印章式狀態、合計雙下劃線），畫布保持乾淨的暖紙色，不鋪任何整頁紋理或規線背景**——後者讀起來像廉價雜訊，且無法承載真正的帳本質感。

### 1.1 設計原則

1. 材料優先：實際耗材顏色是資料標記，不是品牌裝飾。
2. 可追溯：重量、列印任務、耗材對應與成本應能沿著資料線索互相回溯。
3. 低干擾：使用細邊框、低陰影、低圓角，避免把資料包裝成消費性產品卡片。
4. 狀態可理解：狀態不可只靠顏色，必須同時提供文字或圖示。
5. 本機優先：離線或外部字體載入失敗時，介面仍須保持可用。

### 1.2 Bambu 獨立性

- Bambu Cloud 只在登入、同步與資料來源語境出現。
- 不使用 Bambu Logo、產品圖形或仿製設備控制面板。
- 不以 Bambu 品牌橘／藍作為 UI 主色。
- 不使用玻璃擬態、霓虹漸層、發光邊框或過度圓角。
- 任何實際材料顏色只表示資料內容，不表示 Filament Ledger 品牌色。

## 2. 色彩 Token

所有新樣式優先使用 `--ui-*` token；既有 Pico 變數與 `--app-*` 變數只作相容 alias。

### 2.1 Light

| Token | 值 | 用途 |
|---|---|---|
| `--ui-canvas` | `#F2EFE8` | 頁面畫布 |
| `--ui-surface` | `#FFFDF7` | 卡片、表單、側欄 |
| `--ui-surface-2` | `#E9E7DF` | 表頭、次要背景 |
| `--ui-ink` | `#202B29` | 主要文字 |
| `--ui-muted` | `#68736D` | 次要文字 |
| `--ui-border` | `#D4D8CE` | 邊框與分隔線 |
| `--ui-primary` | `#2E6F63` | 主要操作、連結、選取 |
| `--ui-primary-hover` | `#24574F` | 主要操作 hover |
| `--ui-success` | `#2C7A5D` | 可用、成功 |
| `--ui-warning` | `#A66A2C` | 低庫存、注意 |
| `--ui-danger` | `#A84343` | 用盡、錯誤、刪除 |
| `--ui-lime` | `#DDE8C4` | 選取背景、輕提示 |

### 2.2 Dark

Dark 主題使用同名 token 覆蓋為：畫布 `#111917`、表面 `#1B2522`、次要表面 `#24312D`、文字 `#E7ECE4`、次要文字 `#9AA8A0`、邊框 `#33413B`、主色 `#86BEB0`、警示 `#D7A865`、錯誤 `#DF8B8B`。

### 2.3 Ledger token（v1.1）

帳目專用 token，供 `.ledger-table`、出入帳色語與印章 badge 使用。debit/credit 直接沿用 danger/success 家族值以繼承已驗證的 AA 對比。

| Token | Light | Dark | 用途 |
|---|---|---|---|
| `--ui-ledger-rule` | `#E0DDD2` | `#2C3833` | 帳目細橫規線與欄位分隔線 |
| `--ui-ledger-rule-strong` | `#C9CDBF` | `#3D4B44` | 表格外框、表頭與合計列雙下劃線 |
| `--ui-debit` | `= --ui-danger` | `= --ui-danger` | 消耗／出帳數值（暖紅） |
| `--ui-credit` | `= --ui-success` | `= --ui-success` | 結餘／入帳數值（礦物綠） |
| `--ui-stamp-border` | `#9AA093` | `#4E5C54` | 印章式 badge 邊框基底 |

出入帳語意用 `.amount--debit` / `.amount--credit` 套色；狀態 badge 邊框以 `color-mix` 將語意色摻入 `--ui-border`，深淺主題隨 token 自動轉譯，不另寫 dark 覆寫。

### 2.3 狀態

| 狀態 | 語意 | 顯示方式 |
|---|---|---|
| `active` | 使用中／仍可使用 | 綠色文字、圓點、狀態標籤 |
| `low` | 剩餘量偏低 | 赭石文字、警示標籤 |
| `empty` | 已用盡 | 暗紅文字、錯誤標籤 |
| `sealed` | 未開封 | 灰綠文字、低強度標籤 |

實體顏色用 `.color-swatch` 或 `.material-swatch` 顯示，不能取代狀態文字。

## 3. 字體與排版

- 標題：`Noto Serif TC`，fallback `Noto Sans TC`、serif。
- 介面文字：`Noto Sans TC`、`IBM Plex Sans`、`Microsoft JhengHei`、system sans-serif。
- 數值、重量、成本、時間：`IBM Plex Mono`、`Cascadia Mono`、ui-monospace。
- 主要內容最大寬度：`1440px`。
- 內容水平 padding：桌面 `clamp(1.2rem, 3vw, 3.5rem)`；手機 `1rem`。
- 圓角：一般 `6px`，小型控制項 `3px`；避免大面積 pill。
- 陰影只用於卡片 hover、浮層與 sticky panel，不作為每個區塊的裝飾。

## 4. Layout 與導覽

### 4.1 Desktop

`base.html` 使用：

```text
.app-shell
├── .app-sidebar       232px sticky sidebar
└── .app-main-shell
    ├── .app-content
    └── .app-footer
```

導覽分為「總覽、材料、列印、洞察、系統」五個群組。現有 URL 與 `aria-current="page"` 判斷必須保留。

桌面側欄可透過標頭收縮控制切換為 `72px` icon-only 模式，主內容 grid 會同步展開；狀態以 `filament-ledger-sidebar-collapsed` 保存於 `localStorage`（讀取時 fallback 舊 key）。收縮模式下每個導覽連結必須保留 `title` 與可辨識的 icon，控制按鈕需維持鍵盤操作與 `aria-expanded` 狀態同步。導覽群組使用內容高度由上而下排列，不以 `space-between` 撐開空白。

### 4.2 Mobile

寬度 `<= 820px` 時：

- 側欄改為固定底部導覽。
- 只顯示總覽、耗材、列印歷史、分析四個高頻入口。
- Mapping、印表機、成本、設定放入「更多」選單。
- 語言切換保留於設定頁；主題切換仍固定可見。
- 導覽本身可以操作，但不得造成整個頁面水平溢出。

### 4.3 Shell breakpoint

側欄會佔用內容寬度，因此成本雙欄、任務表單與 Dashboard summary 必須在 `821–1100px` 之間提前收合，不能只依賴 viewport 的一般桌面 breakpoint。

## 5. 共用元件

### `page-header`

頁面標題區應包含 eyebrow、標題、說明與操作按鈕。主要操作放右側，手機版改為滿寬排列。

### `status-badge`

使用既有 `.status-*` semantic class，加上文字與狀態圓點。不得只放色塊或 emoji。

### `weight-meter`

由剩餘量、進度條與數值組成。低於 50%、25%、10% 時使用對應 threshold 顏色，並保留數值文字。

### `ledger-table`（v1.1 已實作）

opt-in class（加在 `<table>`），為帳目式表格提供完整帳簿格網：

- 外框 `--ui-ledger-rule-strong`、列橫規線 `--ui-ledger-rule`、欄位以 `td + td` 左緣細直線分隔。
- 文字儲存格左對齊；數值儲存格加 `.num`（右對齊、等寬 `tabular-nums`、`white-space:nowrap` 避免數值與單位斷行）。
- 流水序號欄加 `.seq`（右對齊等寬、次要色）；序號由模板以 `(page-1)*per_page + loop.index` 產生。
- 合計列用 `tfoot` 或 `tr.ledger-total`，呈現 `3px double` 會計式雙下劃線。
- 表面實心 `--ui-surface`，與乾淨畫布區隔。

**契約**：class 只加在 `<table>`/`<th>`/`<td>`，**絕不動 `<tr>`/`<tbody>` fragment 根節點**（HTMX UI API）。大量資料放在 `.overflow-auto` 中。mapping 工作台表格（`.mapping-data-table`）語意為工作面板而非帳目，刻意不套用 `.ledger-table`。

### 數字格式化 filter（v1.1）

所有面向使用者的數值一律透過集中式 Jinja filter（`web/app.py`），取代散落的內聯 `'%.Nf'|format`：

- `fmt_weight(v, unit='g', digits=1)`：千分位＋固定小數＋單位。
- `fmt_money(v, digits=2)`：貨幣符號由 i18n key `cost.money_format` 決定位置（zh 後綴「元」／en 前綴「$」）。
- `fmt_duration(seconds)`：`3h 12m`（不足 1 小時只顯示分鐘）。
- `fmt_int(v)`：千分位整數。
- `ledger_amount(text, kind)`：把已格式化字串包成 `.amount--debit/credit/neutral` span，表達出入帳色語。

例外：CSS 寬度百分比（`width:X%`）與 dashboard 經濟面板的 kg/g 自動切換維持原始格式化（filter 會破壞單位邏輯）。

### 印章式 status badge（v1.1）

`.status-badge` / `.manual-badge` / `.print-status-badge` 統一為方框細邊框印章風（`border-radius:2px`、透明底、uppercase、`letter-spacing`），邊框以 `color-mix` 將語意色摻入 `--ui-border`。取代舊 pill 造型，不使用色塊圓點。

### `status-strip`

用於待 Mapping、低庫存、同步錯誤與成功提示。以短句說明「發生什麼事」與「下一步能做什麼」。

## 6. 頁面規範

### Dashboard

順序固定為：注意事項 → 庫存跑道 → 列印總計 → 最近列印。第一視線應回答「哪些材料需要處理」。

### 材料

使用材料色票、材料類型、剩餘重量、使用比例、最近使用日期與操作欄。狀態分組可保留，但應讓重量與狀態比購買日期更容易掃讀。

### 列印任務

以帳本式紀錄呈現封面、名稱、印表機、時間、耗時、用量與狀態，套用 `.ledger-table` 與流水序號欄。任務詳情中材料欄位使用 `slot → material → spool → used weight` 的追蹤關係，並以 `合計` 雙下劃線列收尾。page-header 的 `.eyebrow` 承載帳本頁眉（如「第 N 頁・共 M 筆」）。

### Mapping

維持「未對照／已對照／已忽略」三個工作狀態。所有 `hx-target`、`hx-swap="outerHTML"` 與 fragment 根節點為 UI API，不得為了視覺包裝而插入額外 wrapper。

### 分析與成本

圖表以資料可讀性優先，使用統一字體、網格線與 tooltip。成本頁保留 sticky summary，但在內容寬度不足時改為上下排列。

### 設定

使用低干擾分區表單。Token、同步、備份與外部資料來源要有清楚的狀態標籤，不把設定頁做成設備控制面板。

## 7. Accessibility 與互動

- `base.html` 必須提供 skip link，跳至 `#main-content`。
- 所有可操作控制項必須是 link、button、form control 或具備完整鍵盤行為的元件。
- `:focus-visible` 必須有清楚 outline。
- 顏色不得是唯一資訊來源。
- HTMX 狀態區域應使用適當的 `aria-live` 或可見成功／錯誤訊息。
- `prefers-reduced-motion: reduce` 時停用非必要動畫。
- Lightbox 需要支援 Escape；後續改善時應補上 focus return／trap。
- 表格標題應使用 `scope="col"`；可橫向捲動的表格必須包在 `.overflow-auto`。

## 8. HTMX 與相容性規則

不得修改下列既有契約：

- `#cost-summary`
- `#cost-gallery`
- `#sync-status-area`
- `#auto-sync-status-area`
- `#backup-status-area`
- `#mat-*`
- Mapping 與任務詳情中的 `<tr>` fragment 根節點

Fragment 不繼承 `base.html`，只回傳裸 HTML。全域 shell 只存在於完整頁面。

## 9. 驗收矩陣

實作完成後至少驗證：

- 所有 route 在繁中／英文可 render，JSON key parity 通過。
- Light／Dark 主題下文字與狀態符合 WCAG AA 基本對比要求。
- 320px、390px、768px、1024px、1440px 寬度沒有頁面級水平溢出。
- Dashboard、材料、任務、Mapping、成本、設定的 HTMX target 不退化。
- 鍵盤可使用 skip link、導覽、側欄切換、材料展開與 Mapping 群組展開。
- `pytest`、Python compileall、print view 與既有圖片 lightbox 行為通過。

## 10. 維護規則

新增 UI 優先：

1. 使用既有 semantic class。
2. 使用 `--ui-*` token，不新增散落 hex 色碼。
3. 共用樣式放 `style.css`，頁面模板只保留資料條件與必要的 HTMX attributes。
4. 新增可見文字時同步更新 `zh.json` 與 `en.json`。
5. 任何 fragment DOM 變更都要附帶 HTMX regression check。

## 變更紀錄

### v1.1

- 產品更名為材料帳本 Filament Ledger；UI 術語「耗材」統一為「材料」。
- 帳本語言收斂到資料本身：移除整頁網點紋理與橫規線背景（讀來像雜訊），畫布回歸乾淨暖紙。
- `.ledger-table` 落地實作：外框、欄位直線分隔、`.num`/`.seq` 欄、`合計` 雙下劃線。
- 新增集中式數字 filter（`fmt_weight`/`fmt_money`/`fmt_duration`/`fmt_int`/`ledger_amount`）與出入帳色語 token。
- status badge 改為印章式方框；page-header eyebrow 承載流水頁眉。

### v1.0

- 建立 Material Ledger 視覺語言。
- 建立礦物綠、溫暖紙張與墨水色 token。
- 導入左側導覽、手機底部導覽與共用 page header。
- 保留 Pico CSS、HTMX、路由、資料庫與既有狀態 class。
