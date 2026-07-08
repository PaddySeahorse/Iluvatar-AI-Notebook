# 计划：将所有 CDN 资源本地化

## 摘要 (Summary)

将 [static/index.html](file:///workspace/static/index.html) 中所有外部 CDN 引用（Font Awesome、Google Fonts、CodeMirror）下载到本地 `static/vendor/` 目录，并把 HTML 中的外链全部替换为本地路径，使应用在完全离线环境下也能正常加载样式与脚本。

---

## 当前状态分析 (Current State Analysis)

### CDN 引用清单（共 3 个外部来源，9 处引用）

来源：[static/index.html](file:///workspace/static/index.html)

| # | 行号 | 来源域 | 资源 |
|---|------|--------|------|
| 1 | L8  | cdnjs.cloudflare.com | Font Awesome 6.4.0 `all.min.css` |
| 2 | L10 | fonts.googleapis.com | `<link rel="preconnect">` |
| 3 | L11 | fonts.gstatic.com   | `<link rel="preconnect">` |
| 4 | L12 | fonts.googleapis.com | Inter + Fira Code 字体 CSS |
| 5 | L15 | cdnjs.cloudflare.com | CodeMirror `codemirror.min.css` |
| 6 | L16 | cdnjs.cloudflare.com | CodeMirror theme `dracula.min.css` |
| 7 | L17 | cdnjs.cloudflare.com | CodeMirror theme `neo.min.css` |
| 8 | L343| cdnjs.cloudflare.com | CodeMirror `codemirror.min.js` |
| 9 | L344| cdnjs.cloudflare.com | CodeMirror `mode/python/python.min.js` |
| 10| L345| cdnjs.cloudflare.com | CodeMirror `mode/markdown/markdown.min.js` |

### 间接依赖（必须一并下载）

- **Font Awesome**：`all.min.css` 内通过相对路径 `./webfonts/*.woff2` 引用 webfont 文件（`fa-solid-900.woff2`、`fa-regular-400.woff2`、`fa-brands-400.woff2`）。必须保留 `css/` + `webfonts/` 目录结构。
- **Google Fonts**：googleapis 返回的 CSS 中通过绝对 URL `https://fonts.gstatic.com/...` 引用若干 woff2 字体文件。Inter 需要 6 个 weight（300/400/500/600/700），Fira Code 需要 2 个 weight（400/500），每个 weight 还分 latin / latin-ext / cyrillic 子集。为简化，只下载 **latin 子集**（项目仅中英文，无西里尔文需求），并自行编写 `@font-face` 声明。
- **CodeMirror**：python / markdown mode 依赖 `codemirror.min.js` 先加载（当前顺序已正确，保持不变即可）。

### 静态文件服务

[core/routes/static_routes.py](file:///workspace/core/routes/static_routes.py) 通过 `/static/<path:path>` 路由用 `send_from_directory` 提供静态文件，[app.py#L50](file:///workspace/app.py#L50) 设置 `static_folder='static'`。因此放在 `static/vendor/` 下的文件可直接通过 `/static/vendor/...` 访问，无需修改后端代码。

### 字体使用情况

[static/style.css](file:///workspace/static/style.css) 第 26-27 行定义：
```css
--font-ui: 'Inter', system-ui, -apple-system, sans-serif;
--font-code: 'Fira Code', monospace;
```
本地化后字体 family 名称不变（在 `@font-face` 中声明 `font-family: 'Inter'` / `'Fira Code'`），所以 **style.css 无需修改**。

---

## 实施步骤 (Proposed Changes)

### 步骤 1：创建 vendor 目录结构

```
static/vendor/
├── font-awesome/
│   ├── css/all.min.css
│   └── webfonts/  (fa-solid-900.woff2, fa-regular-400.woff2, fa-brands-400.woff2)
├── codemirror/
│   ├── codemirror.min.css
│   ├── codemirror.min.js
│   ├── theme/dracula.min.css
│   ├── theme/neo.min.css
│   └── mode/
│       ├── python/python.min.js
│       └── markdown/markdown.min.js
└── fonts/
    ├── fonts.css          (自写的 @font-face 声明)
    ├── inter/
    │   ├── inter-latin-300.woff2
    │   ├── inter-latin-400.woff2
    │   ├── inter-latin-500.woff2
    │   ├── inter-latin-600.woff2
    │   └── inter-latin-700.woff2
    └── fira-code/
        ├── fira-code-latin-400.woff2
        └── fira-code-latin-500.woff2
```

### 步骤 2：下载资源（用 curl）

#### 2.1 Font Awesome 6.4.0
```bash
mkdir -p static/vendor/font-awesome/css static/vendor/font-awesome/webfonts
curl -fsSL -o static/vendor/font-awesome/css/all.min.css \
  https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css
for f in fa-solid-900 fa-regular-400 fa-brands-400; do
  curl -fsSL -o static/vendor/font-awesome/webfonts/$f.woff2 \
    https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/$f.woff2
done
```

#### 2.2 CodeMirror 5.65.13
```bash
mkdir -p static/vendor/codemirror/theme static/vendor/codemirror/mode/python static/vendor/codemirror/mode/markdown
base=https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13
curl -fsSL -o static/vendor/codemirror/codemirror.min.css $base/codemirror.min.css
curl -fsSL -o static/vendor/codemirror/codemirror.min.js  $base/codemirror.min.js
curl -fsSL -o static/vendor/codemirror/theme/dracula.min.css $base/theme/dracula.min.css
curl -fsSL -o static/vendor/codemirror/theme/neo.min.css     $base/theme/neo.min.css
curl -fsSL -o static/vendor/codemirror/mode/python/python.min.js   $base/mode/python/python.min.js
curl -fsSL -o static/vendor/codemirror/mode/markdown/markdown.min.js $base/mode/markdown/markdown.min.js
```

#### 2.3 Google Fonts（Inter + Fira Code）
googleapis 返回的 CSS 随 User-Agent 变化，且字体文件在 `fonts.gstatic.com`。直接用 `curl -A` 拿到 woff2 的 CSS，再从中提取 woff2 URL 下载。

```bash
mkdir -p static/vendor/fonts/inter static/vendor/fonts/fira-code
# Inter (latin 子集, 5 个 weight)
css=$(curl -fsSL -A "Mozilla/5.0" \
  "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap")
echo "$css" > /tmp/inter.css
# Fira Code (latin 子集, 2 个 weight)
css=$(curl -fsSL -A "Mozilla/5.0" \
  "https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&display=swap")
echo "$css" > /tmp/fira.css
```
然后从抓到的 CSS 中解析出 `https://fonts.gstatic.com/...woff2` 链接，按 weight 下载到 `static/vendor/fonts/inter/` 和 `static/vendor/fonts/fira-code/`，并保留 weight→文件名映射。

### 步骤 3：编写本地字体 CSS

新建 `static/vendor/fonts/fonts.css`，把 googleapis 返回的 `@font-face` 块改写为引用本地 woff2 文件（去掉 `unicode-range` 限制或保留 latin 子集范围均可，简化处理：去掉 latin-ext / cyrillic 的 `@font-face`，只保留 latin）。family 名称保持 `'Inter'` 和 `'Fira Code'` 以兼容现有 style.css。

### 步骤 4：重写 [static/index.html](file:///workspace/static/index.html)

**替换 L7-L17（head 中的外部资源）：**

原：
```html
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="static/style.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/codemirror.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/theme/dracula.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/theme/neo.min.css">
```
改为：
```html
<link rel="stylesheet" href="static/vendor/font-awesome/css/all.min.css">
<link rel="stylesheet" href="static/vendor/fonts/fonts.css">
<link rel="stylesheet" href="static/style.css">
<link rel="stylesheet" href="static/vendor/codemirror/codemirror.min.css">
<link rel="stylesheet" href="static/vendor/codemirror/theme/dracula.min.css">
<link rel="stylesheet" href="static/vendor/codemirror/theme/neo.min.css">
```
（删除两个 `preconnect`，已无外部域可预连接。）

**替换 L343-L345（body 末尾的脚本）：**

原：
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/mode/python/python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.13/mode/markdown/markdown.min.js"></script>
```
改为：
```html
<script src="static/vendor/codemirror/codemirror.min.js"></script>
<script src="static/vendor/codemirror/mode/python/python.min.js"></script>
<script src="static/vendor/codemirror/mode/markdown/markdown.min.js"></script>
```

---

## 假设与决策 (Assumptions & Decisions)

1. **完全替换 CDN**，不保留任何外链 fallback。离线可运行。
2. **vendor 目录命名**：`static/vendor/`（行业惯例，便于识别第三方资源）。
3. **Google Fonts 仅下载 latin 子集**，去掉 latin-ext / cyrillic，减少文件数。中文不通过 Google Fonts 渲染（页面中文字符由系统字体兜底），不影响效果。
4. **不改后端**：`/static/<path>` 路由已能服务 vendor 子目录，无需修改 [core/routes/static_routes.py](file:///workspace/core/routes/static_routes.py)。
5. **不改 style.css**：通过在 `fonts.css` 中保持 `font-family: 'Inter'/'Fira Code'` 名称兼容。
6. **网络可达性**：实施时需 sandbox 能访问 `cdnjs.cloudflare.com` 与 `fonts.googleapis.com` / `fonts.gstatic.com`。若实施环境无法联网，需改用预置离线包或人工上传。
7. **CodeMirror 加载顺序**保持 core → python mode → markdown mode，与现状一致。

---

## 验证 (Verification)

1. **静态资源齐全**：`ls -R static/vendor/` 确认所有文件存在且非空。
2. **HTML 无外链**：grep 检查 [static/index.html](file:///workspace/static/index.html) 不再含 `https://cdnjs` 或 `https://fonts.`：
   ```bash
   grep -nE 'https://(cdnjs|fonts)' static/index.html
   # 期望：无输出
   ```
3. **运行测试**：执行 `pytest`（[tests/test_app.py](file:///workspace/tests/test_app.py)），确保未破坏现有路由测试。
4. **启动应用**：`python app.py`，浏览器打开 `http://localhost:5000/`：
   - Font Awesome 图标正常显示（齿轮、文件夹、机器人等）。
   - Inter / Fira Code 字体应用（开发者工具 → Network 无外部域请求）。
   - CodeMirror 编辑器可正常编辑 Python / Markdown，dracula / neo 主题可切换。
   - Network 面板全部请求均指向 `localhost`，无任何 `cdnjs` / `googleapis` / `gstatic` 请求。
