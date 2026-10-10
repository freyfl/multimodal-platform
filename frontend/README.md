# 多模态检索平台 · 前端

Vue 3 + TypeScript + Vite 7 + Ant Design Vue 4。本目录只包含浏览器端；后端与基础设施见仓库根目录 `README.md`。

## 本地运行

```bash
npm install
npm run dev          # 默认 http://127.0.0.1:5173，可用 --port 指定
npm run type-check   # vue-tsc
npm test             # node:test 单元测试
npm run build        # 产物输出到 dist/
```

开发服务器通过 `vite.config.ts` 中的代理把 `/api` 转发到后端（默认 `http://127.0.0.1:8000`）。

## 设计语言

界面围绕「感知工作台」这一隐喻构建：墨色（ink）承载结构与品牌面，薄荷绿（mint）只用于品牌识别与选中态，钴蓝（cobalt）是**唯一**的交互色，其余一律保持中性。所有取值都在 `src/assets/styles/variables.css` 中定义为 CSS 变量，组件不应再写死色值。

| 角色 | 变量 | 用途 |
| --- | --- | --- |
| 墨色 | `--ink` `--ink-2` `--ink-3` `--ink-line` | 侧栏、首个统计卡、选中 chip、Tooltip、分页当前页 |
| 薄荷 | `--mint` `--mint-soft` `--mint-deep` `--mint-ink` | 品牌标记、侧栏激活项、完成态徽标、图标 hover |
| 钴蓝 | `--color-primary*` | 按钮、链接、聚焦环、运行中态 |
| 中性 | `--gray-50 … --gray-900` | 带轻微墨绿倾向的灰阶，背景 / 边框 / 文字 |

### 版式

- 界面文案一律使用中文；英文 / 等宽字体只用于数字、编号、ID、路径、版本号等机器可读内容。
- 标题：`Exo 2`（`--font-heading`），正文 `Noto Sans SC`，编号 / 数值 / 路径使用 `Roboto Mono`（`--font-mono`）。中文小标签（眉题、表头、分类名）用正文字体 11px + 0.14–0.22em 字距，不用 `text-transform`。
- 每个页面头部统一使用 `PageHeader`：眉题（`多模态工作台 / …`）→ 标题（结尾钴蓝句点）→ 副标题。
- Ant Design 全局 locale 为 `zh_CN`（分页、日期、空态等内置文案均为中文）。
- 数字使用 `font-variant-numeric: tabular-nums` 与 `--tracking-numeric`，统计卡数值滚动计数。

### 动效

- 缓动与时长只用 token：`--ease-out`（入场）、`--ease-spring`（图标 / 勾选等小元素）、`--duration-fast|normal|slow|reveal`。
- 动效只保留给**入场**和**可操作元素**：页面进入淡入上移、侧栏导航错落入场、登录页标题遮罩揭示、感知图形描边自绘 + 慢速扫描。
- 全部动效遵守 `prefers-reduced-motion`。

### 原创图形

`PerceptionGraphic.vue` 中的透视场、立方体与取景角标是品牌的视觉签名，出现在登录页、概览页头部；`EmptyState` 复用取景角标；品牌标记统一使用不对称圆角 `--radius-mark`。

### 响应式

断点：`960px`（侧栏折叠为抽屉）、`768px`、`600px`。页面水平留白用 `--page-gutter`（`clamp(24px, 3.4vw, 64px)`），内容最大宽 `--content-max`。表格在窄屏下横向滚动，空态保持可见。
