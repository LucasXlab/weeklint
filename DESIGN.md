# 周检 Weeklint 报告页设计规范

本文件只覆盖 `plan` 生成的单文件 HTML 周报（`report.html`）。CLI 终端输出另见 SPEC 第 12 节的文字规则。页面不是 Web 应用：没有路由、没有表单、没有 JavaScript、没有网络请求；打开即读，读完即关。

设计目标：让第一次打开的人在 5 秒内看到「这周装不装得下」，在 30 秒内看到「哪几个任务危险、排在哪」。不追求视觉冲击，追求信息密度、可扫描性和打印可用。

## 0. 要去掉的东西

以下是 AI 生成界面的常见毛病，本页面一条都不出现：

1. **渐变卡片、玻璃拟态、发光边框。** 不用任何 `linear-gradient`、`backdrop-filter`、彩色阴影。
2. **标题前的彩色图标方块。** 页面标题、区块标题前都不放图标；没有图标库。
3. **每个标题下都跟一句解释。** 标题能看懂就不解释；只有「容量」这种需要口径的区块，用一行小字写公式。
4. **胶囊形徽章。** 状态用「圆点 + 文字」，不用全圆角标签；`border-radius` 不超过 12px（按钮/小标签 4–6px）。
5. **到处都是 emoji。** 页面零 emoji；状态靠文字、颜色、字重区分。
6. **卡片套卡片。** 一个区块只有一层边界；不在卡片里再放卡片。
7. **空洞的大号引导页 / Hero。** 首屏直接是周范围、三个关键数字和 findings，没有「欢迎使用」。
8. **原生下拉框、原生日期选择器、原生复选框。** 页面没有任何表单控件，所以也不会出现系统控件。
9. **大面积纯黑/纯白 + 高饱和主色。** 背景是暖白/近黑，主色是低饱和墨绿；语义色只用于状态。
10. **无意义的插图、3D 图标、装饰性网格。** 没有图片资源；唯一的图形是容量条和状态圆点。
11. **所有文字都加粗、所有数字都放大。** 只有页面标题、三个关键数字、当前进行中的块允许加粗/放大。
12. **悬停才显示关键信息。** 关键信息默认可见；`title` 属性只用于补充说明，不承载唯一信息。
13. **自动播放/滚动动画。** 没有动画，只有 `prefers-reduced-motion` 下的 0 时长；页面加载不滚动。
14. **伪数据图表。** 容量条按真实分钟数计算宽度；没有数据就显示「无」，不画装饰性柱状图。
15. **页脚放社交链接/版权大段。** 页脚只有一行「本地生成，没有上传数据」和版本号。

## 1. 实现方式

- 单文件 HTML：`<style>` 内联；不引用外部 CSS、JS、字体、图片、CDN。
- 无 `<script>`；无 `onclick`；无 `javascript:` URL。
- 样式用 CSS 变量（token）+ 一组语义类；不使用 Tailwind/组件库。
- 类名用 BEM 风格：`.week`, `.week__day`, `.metric--danger`。
- 页面 CSS 只引用 token；不允许出现硬编码的颜色、字号、圆角、阴影。唯一例外：`width`/`grid-template-columns` 等布局数值和 1px 边框。
- 字体：系统字体栈，不加载外部字体：
  `-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif`
- 数字用 `font-variant-numeric: tabular-nums`。
- 深色模式跟随 `prefers-color-scheme`；不提供手动切换。
- 打印：A4 纵向，隐藏页脚按钮（没有按钮）和颜色背景，保留文字和边框；避免在块中间断页。

## 2. Token

### 2.1 颜色（浅色 / 深色）

| 变量 | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--bg` | `#fbfbfa` | `#111311` | 页面底色 |
| `--surface` | `#ffffff` | `#171a17` | 区块底色 |
| `--surface-subtle` | `#f4f4f0` | `#1d211d` | 表头、容量条底、空状态 |
| `--border` | `#e3e3dd` | `#2b302b` | 默认分隔线 |
| `--border-strong` | `#c9c9c1` | `#444b44` | 重点分隔、容量条边框 |
| `--text` | `#1c1c1a` | `#eceee9` | 正文 |
| `--text-muted` | `#5f5f5a` | `#a7aba3` | 次要文字、日期、说明（对比度 ≥ 4.5:1） |
| `--text-faint` | `#8a8a83` | `#6f756e` | 仅用于禁用/不承载必要信息的文字 |
| `--accent` | `#1f5f4a` | `#7fc9aa` | 主色：当前块、容量条填充、链接 |
| `--accent-weak` | `#e7f1ec` | `#1b2e26` | 主色浅底 |
| `--danger` | `#a02a2a` | `#f08a8a` | 装不下、截止风险 |
| `--danger-weak` | `#f8e9e9` | `#321c1c` | 风险浅底 |
| `--warning` | `#8a5a00` | `#e0b36a` | 警告 |
| `--warning-weak` | `#f8f0df` | `#302616` | 警告浅底 |
| `--ok` | `#2f6b45` | `#8fd3ad` | 装得下、已完成 |
| `--ok-weak` | `#e9f2ec` | `#1a2a20` | 成功浅底 |
| `--focus` | `#2563eb` | `#60a5fa` | 键盘焦点环 |

- 正文/次要文字对背景的对比度：浅色 `#1c1c1a` on `#fbfbfa` = 16.5:1；`#5f5f5a` on `#fbfbfa` = 6.2:1；深色 `#eceee9` on `#111311` = 16.0:1；`#a7aba3` on `#111311` = 8.0:1。均 ≥ 4.5:1。
- 语义色只表达状态，不用于装饰；任何状态同时有文字，不单靠颜色。
- 不使用渐变、透明叠加色、彩色阴影。

### 2.2 字号与字重

| Token | 字号 / 行高 | 字重 | 用途 |
|---|---|---|---|
| `--text-xs` | 12px / 16px | 400 | 页脚、容量公式、辅助说明 |
| `--text-sm` | 13px / 20px | 400 | 表格、元信息、标签 |
| `--text-base` | 14px / 22px | 400 | 正文、任务标题 |
| `--text-md` | 16px / 24px | 500 | 区块标题、日期 |
| `--text-lg` | 20px / 28px | 600 | 页面标题 |
| `--text-metric` | 32px / 38px | 600 | 三个关键数字（桌面） |
| `--text-metric-sm` | 28px / 34px | 600 | 三个关键数字（≤639px） |
| `--text-print` | 11pt / 1.45 | 400 | 打印正文（不小于 11pt） |
| `--text-week` | 15px / 22px | 500 | 周范围 |

- 字重只用 400 / 500 / 600；不用 700/800。
- 页面标题、指标、日期加 `letter-spacing: -0.01em`；正文不加。
- 中文不设 `text-transform`；英文标签不大写。

### 2.3 间距、圆角、边框、阴影、动效

- 间距阶梯：4 / 8 / 12 / 16 / 24 / 32 / 48 / 64px。页面左右边距：桌面 32px，≤640px 16px。
- 圆角：
  - `--radius-sm: 4px`：状态标签、容量条；
  - `--radius-md: 6px`：小按钮/块；
  - `--radius-lg: 8px`：区块、日列；
  - `--radius-xl: 12px`：仅用于整页最大容器（可选）。
  - 禁止 `border-radius: 999px` / 胶囊。
- 边框：默认 `1px solid var(--border)`；重点 `1px solid var(--border-strong)`；不用彩色边框装饰。
- 阴影：**只有浮层允许**。本页没有浮层，因此 `box-shadow: none`。不使用卡片投影。
- 动效：本页无动画。若未来加，只允许 120ms（颜色）和 180ms（展开），并尊重 `prefers-reduced-motion: reduce`。
- 容量条：高 8px，圆角 `--radius-sm`，底 `--surface-subtle`，填充 `--accent`；超载时填充 `--danger`；宽度按 `min(100%, scheduled/capacity*100%)` 计算（已排分钟 / 可排分钟），右侧文字写「已排 14h20m / 可排 18h30m」。`capacity=0` 时宽度 0，文字写「本周没有可用时间」。

### 2.4 栅格与断点

- 桌面 ≥1024px：内容最大宽度 1120px，居中；周计划 7 列，列间距 12px。
- 640–1023px：周计划 2 列；摘要两列，第三个指标跨两列。
- <640px（含 375px）：单列；周计划按天纵向堆叠；摘要两列，第三个指标跨两列；表格改为「日期 + 块」的列表。
- 断点只写 `@media (max-width: 639px)` 和 `@media (min-width: 1024px)`；不做 4 套以上。
- 375px 下：页面左右 16px；标题 20px；指标 28px；时间块内边距 12px；不出现横向滚动；长任务标题 `overflow-wrap: anywhere`。

### 2.5 必须出现的 token 清单

测试 `test_report.py` 至少断言以下变量在 HTML 的 `:root` 中出现：`--bg`、`--surface`、`--surface-subtle`、`--border`、`--border-strong`、`--text`、`--text-muted`、`--accent`、`--accent-weak`、`--danger`、`--danger-weak`、`--warning`、`--warning-weak`、`--ok`、`--ok-weak`、`--text-base`、`--text-sm`、`--text-xs`、`--text-md`、`--text-lg`、`--text-metric`、`--text-metric-sm`、`--text-print`、`--radius-sm`、`--radius-md`、`--radius-lg`。

## 3. 页面结构

从上到下：

1. **页头**（`header`）
   - 左：`周检` 小字品牌（13px，`--text-muted`）+ 页面标题「2026 年第 45 周」（20px）；下一行周范围 `11月2日–11月8日`（15px，`--text-muted`）。
   - 右：`生成于 11月1日 20:00`（12px，`--text-muted`）；窄屏移到标题下方。
   - 底边 1px `--border`。
2. **摘要条**（`section.summary`）
   - 三个指标：`可支配`、`任务需要`、`缺口`。
   - 每个指标：数字（桌面 32px，≤639px 28px；缺口为 0 时用 `--ok`，>0 用 `--danger`）+ 单位「小时/分钟」小字 + 标签。三个指标口径固定：`可支配 = capacity.usableMinutes`、`任务需要 = demand.estimatedMinutes`、`缺口 = gapMinutes`（都来自 `check`/`plan` 的同名字段）。
   - 指标下方一条容量条；右侧文字「已排 14h20m / 可排 18h30m」，其中已排=`summary.scheduledMinutes`，可排=`summary.capacityMinutes`；`capacity=0` 时宽度 0，文字「本周没有可用时间」。
   - 只有 `summary.tasksUnscheduled == 0` 且没有任何 `severity=error` 的 finding 时，才显示「这周装得下。」；否则显示「有任务未排完，见下方。」。
3. **发现**（`section.findings`）
   - 有 error/warning 时标题「需要处理」；只有 info 时标题「提醒（N）」并展示 info；完全没有 finding 时标题「没有问题」。
   - 每条：状态圆点（6px）+ 严重度文字（`装不下` / `截止风险` / `提醒`）+ 一句具体说明。
   - 最多显示 12 条；更多时最后一行「还有 N 条，见 plan.json」。
   - 不用手风琴；默认全部展开。
4. **周计划**（`section.week`）
   - 7 列（周一到周日）；每列顶部：`周一` + `11-02`，下面一行 `可用 4h30m`（12px，muted）；「可用」固定取 `days[].usableMinutes`，不是 `freeMinutes`；`include_weekends=false` 的周末仍显示列，写 `不排周末`，不写 0 分钟。
   - 每列内按时间顺序列块：`09:00–10:30`（12px，tabular）+ 任务标题（14px，500）+ 分钟数（12px，muted）。
   - 高优先级块左侧 2px `--accent` 竖线；锁定块右上角文字「已锁定」（12px，muted），不用图标。
   - 当前时间所在块（只有当天且 `now` 在块内）加 `--accent-weak` 底，左侧 2px `--accent`。
   - 没有块的日期：一行 `无安排。`（13px，muted）。
   - 超过 4 个块时自然撑高，不滚动。
5. **未排程**（`section.unscheduled`）
   - 标题「未排程」+ 数量。
   - 每条：任务标题、剩余分钟、原因（`本周容量不足` / `每日高优先级上限` / `每日任务数上限`）。
   - 为空时显示「无。所有任务都排进了本周。」。
6. **页脚**
   - 一行：`由 Weeklint 0.1.0 在本地生成 · 没有上传任何数据 · 不构成对完成时间的保证`。
   - 12px，muted，顶部 1px 边框。

### 3.1 空状态

- 没有任务：摘要显示 `0`，周计划每天「无安排。」，未排程「无任务。请在 tasks.md 里添加任务。」。只有「有任务但全部排下」时才显示「无。所有任务都排进了本周。」。
- 没有日历：周计划按全空闲显示，发现区一条「没有日历文件，本周按全空闲计算。」。
- 装不下：缺口数字红色，发现区第一条「装不下」，未排程区列出具体任务，不隐藏任何块。
- 计划生成失败：不生成 HTML；CLI 报错。页面不存在「加载中」状态。

## 4. 组件规则

- **区块（`.panel`）**：`--surface` 底，1px `--border`，圆角 `--radius-lg`，内边距 24px（窄屏 16px）；标题 16px/500；标题与内容间距 16px。区块之间间距 24px。
- **指标（`.metric`）**：无卡片边框；数字 + 标签 + 可选说明。数字 `--text-metric`，标签 13px muted。三个指标之间用 1px 竖线分隔（窄屏 2×2 时用横线）。
- **状态（`.status`）**：6px 圆点 + 13px 文字；圆点颜色 `--danger` / `--warning` / `--ok` / `--text-muted`；文字必须写出状态名。
- **标签（`.tag`）**：13px，`--surface-subtle` 底，`--text-muted` 字，`--radius-sm`，左右 6px，上下 2px；不用于状态，只用于任务标签；最多显示 3 个，更多写 `+N`。
- **时间块（`.block`）**：`--surface-subtle` 底，`--radius-md`，内边距 12px；时间 12px，标题 14px/500；不嵌套卡片；块之间 8px。
- **表格**：只在桌面端用于「未排程」和「按天明细」；表头 12px/500 muted，行 13px，行间 1px 线；不用斑马纹。
- **链接**：`--accent`，下划线只在 hover/focus；不用于装饰。
- **焦点**：`:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }`；页面没有交互元素，但保留规则。
- **打印**：`@media print` 去掉背景色、圆角、阴影；字号不小于 11pt；日列改为纵向；页脚保留。

## 5. 375px 布局

- 页面 `padding: 16px`；页头纵向排列。
- 摘要：`grid-template-columns: 1fr 1fr`；第三个指标跨两列；指标数字用 `--text-metric-sm`（28px）。
- 周计划：`grid-template-columns: 1fr`；每天一个区块，标题 `周一 11-02 · 可用 4h30m`；块不再显示分钟数（标题够长时省略，避免拥挤）。
- 未排程：标题与原因上下排列；长标题 `overflow-wrap: anywhere`。
- 页脚换行，最多 3 行。
- 禁止横向滚动：`html, body { max-width: 100%; overflow-x: hidden; }`，但不用 `overflow: hidden` 裁掉内容。
- 触控目标：本页没有按钮；若未来加链接，最小 44×44px。

## 6. 可访问性

- `lang="zh-CN"`；标题层级 `h1` → `h2`，不跳级。
- 每个区块有 `aria-labelledby` 指向自己的标题；周计划每天有 `aria-label="周一 11月2日"`。
- 颜色不是唯一信息：每个状态都有文字；容量条有 `role="img"` 和 `aria-label`，写出具体分钟。
- 对比度按 2.1 的数值；不用 `--text-faint` 承载必要信息。
- 支持 200% 缩放；375px 下不横向滚动；打印可读，正文不小于 `--text-print`（11pt）。
- 不做键盘陷阱；没有弹窗/下拉。

## 7. 文案

- 标题：`2026 年第 45 周`；副标题：`11月2日–11月8日`。
- 指标标签：`可支配`、`任务需要`、`缺口`。
- 状态：`装不下`、`截止风险`、`提醒`、`正常`。
- 未排程原因：`本周容量不足`、`每日高优先级上限`、`每日任务数上限`。
- 页脚：`由 Weeklint 0.1.0 在本地生成 · 没有上传任何数据 · 不构成对完成时间的保证`。
- 不用「智能」「一键」「轻松」「高效」「赋能」「升级」这类词；不承诺「一定完成」。
