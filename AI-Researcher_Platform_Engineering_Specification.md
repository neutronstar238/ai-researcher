# AI-Researcher 自动科研平台全栈工程规格

> 文档类型：可直接交给代码生成模型执行的产品、UI、前端、后端、数据与部署统一规格  
> 文档版本：1.0  
> 基准日期：2026-08-16  
> 基准界面：1440 × 900 桌面端  
> 目标读者：Codex、DeepSeek、软件工程 Agent、前端/后端/测试/运维工程师

---

## 0. 文档使用规则

### 0.1 最终目标

从零实现一个可实际运行的 AI-Researcher 自动科研平台。两张参考界面不是静态展示稿，而是平台功能入口：所有可见按钮、筛选器、菜单、状态、数字、图表、节点、表格、上传区和操作项都必须接入真实的前端状态、后端接口、持久化数据或异步任务。禁止以静态 HTML、随机数据、仅前端 Mock、空按钮、永远成功的假接口冒充完成。

平台必须完整支持以下闭环：

```text
创建研究项目
  -> 选题发现与人工确认
  -> 文献检索、上传、解析与证据抽取
  -> 可证伪假设管理
  -> 实验设计、执行、日志与产物管理
  -> 结果验证与矛盾证据处理
  -> 证据约束的论文写作与引用
  -> 研究复盘
  -> 创建下一研究周期
```

### 0.2 需求优先级

代码生成模型必须按以下优先级处理冲突：

1. 本文的“强制”“必须”“禁止”和验收标准。
2. 本文的接口、数据模型、状态机和权限规则。
3. 两张参考界面的视觉关系及本文的像素级参数。
4. 所选框架的默认行为。

不得用框架默认 Dashboard、Ant Design 默认布局或自行“美化”替换本文指定的视觉结构。

### 0.3 已固定的工程决策

- 采用前后端分离。
- V1 后端采用“模块化单体 API + 独立异步 Worker”，不是一开始拆成大量微服务。
- PostgreSQL 是业务事实的权威数据源。
- Neo4j 是知识/证据关系的查询投影，不作为唯一事实源。
- Milvus 保存向量索引；PostgreSQL 保存向量记录的业务元数据和 `vector_ref`。
- MinIO 保存 PDF、数据集、代码快照、日志归档、模型、图表、导出文件等二进制对象。
- Redis 用于缓存、限流、短期状态、Celery Broker 和任务结果通知；不可作为长期事实源。
- 所有跨存储同步通过事务 Outbox 事件完成，不允许在同一请求中进行无法回滚的脆弱双写。
- 外部论文源、LLM、Embedding、OCR 和计算执行器均通过适配器接入；没有凭据时必须显示“未配置”，不得返回伪造成功结果。

### 0.4 V1 范围与非目标

V1 必须是单团队可部署、支持多项目、多用户协作的完整平台。V1 不要求实现公共科研社交网络、计费系统、模型训练云市场、跨区域多活或移动原生 App。桌面浏览器是第一优先级；移动端只需提供可读的降级布局。

### 0.5 完成定义

只有同时满足以下条件，才能宣称某个功能完成：

- 可从 UI 进入并完成正常路径。
- 对应 API 有 OpenAPI 定义、鉴权和权限检查。
- 数据可持久化，刷新页面后保持一致。
- 有明确的 loading、empty、success、error、permission-denied 状态。
- 关键操作写入审计日志。
- 自动化测试覆盖正常路径与至少一个失败路径。
- 异步功能可以查看进度、失败原因并安全重试。
- 不存在未说明的 `TODO`、空处理器、假成功响应或不可点击控件。

---

## 1. 产品模型与用户角色

### 1.1 核心业务对象

| 对象 | 定义 |
|---|---|
| Team | 用户协作和数据隔离边界 |
| Project | 一个长期研究主题 |
| Research Cycle | 项目的一次完整研究迭代 |
| Lifecycle Stage | 选题、文献、假设、实验、验证、写作、复盘、进化之一 |
| Topic Candidate | Discovery Agent 生成、待人工选择的选题候选 |
| Paper | 外部检索或用户上传的文献元数据 |
| Evidence Node | 问题、论文、证据、假设、实验、结果、主张等可追溯节点 |
| Evidence Edge | 节点间支持、反驳、来源、验证等有方向的关系 |
| Experiment | 可重复执行的实验定义 |
| Experiment Run | 某组参数、代码和环境下的一次具体运行 |
| Asset | 文件、数据集版本、代码快照、模型、图表或导出物 |
| Agent | 具备明确职责、工具和权限的智能体配置 |
| Agent Task | 一次可追踪、可暂停、可审批、可重试的 Agent 执行 |
| Document | 论文或报告文档 |
| Approval | 对高风险动作、阶段推进或研究结论的人工审批 |

### 1.2 项目角色

| 能力 | Owner | Researcher | Reviewer | Guest |
|---|:---:|:---:|:---:|:---:|
| 查看项目、文献、图谱 | 是 | 是 | 是 | 是 |
| 修改项目和阶段内容 | 是 | 是 | 仅评论 | 否 |
| 上传文献和数据 | 是 | 是 | 否 | 否 |
| 创建/运行实验 | 是 | 是 | 否 | 否 |
| 启动 Agent | 是 | 是 | 仅 Review Agent | 否 |
| 审批阶段和高风险操作 | 是 | 按授权 | 是 | 否 |
| 管理成员与角色 | 是 | 否 | 否 | 否 |
| 删除/归档项目 | 是 | 否 | 否 | 否 |

服务端必须逐请求执行权限检查；隐藏前端按钮不能替代服务端鉴权。

---

## 2. 技术栈与版本基线

### 2.1 前端

| 类别 | 选型 |
|---|---|
| 基础 | React 18、TypeScript 5、Vite |
| 路由 | React Router 6 |
| 服务端状态 | TanStack Query 5 |
| 轻量客户端状态 | Zustand |
| 表单 | React Hook Form + Zod |
| 样式 | Tailwind CSS + CSS Variables |
| 基础控件 | Ant Design 5，仅使用表单、弹窗、日期、菜单等原子能力，并统一覆写主题 |
| 图表 | Apache ECharts 5 |
| 证据图 | React Flow 12 |
| 图标 | Lucide React；禁止混用多套图标 |
| 单元/组件测试 | Vitest + React Testing Library + MSW |
| 端到端/视觉回归 | Playwright |

### 2.2 后端与基础设施

| 类别 | 选型 |
|---|---|
| API | Python 3.12、FastAPI、Pydantic 2 |
| ORM/迁移 | SQLAlchemy 2、Alembic |
| 异步任务 | Celery 5 + Redis |
| 主数据库 | PostgreSQL 16 |
| 图查询投影 | Neo4j 5 |
| 向量库 | Milvus 2.x |
| 对象存储 | MinIO |
| 文献解析 | PyMuPDF；扫描件走可插拔 OCR Provider |
| 身份认证 | JWT Access Token + 旋转 Refresh Token；密码使用 Argon2id |
| 可观测性 | OpenTelemetry、Prometheus、Grafana、Loki 或兼容实现 |
| 容器 | Docker Compose；生产可迁移至 Kubernetes |

### 2.3 版本策略

- 锁定依赖版本并提交 lockfile。
- API 路径统一以 `/api/v1` 开头。
- 数据库变更只能通过 Alembic migration。
- 前端不得直接依赖数据库结构；只依赖 OpenAPI 生成或手写的稳定 API 类型。

---

## 3. 总体架构

### 3.1 运行时拓扑

```text
Browser
  |
  | HTTPS / WebSocket
  v
Reverse Proxy
  |-----------------------> Frontend static assets
  |
  v
FastAPI API
  |-- Auth / Team / Project / Lifecycle
  |-- Literature / Evidence / Experiment
  |-- Agent / Writing / Approval / Audit
  |
  |---- PostgreSQL (authoritative business state)
  |---- Redis (cache, broker, rate limit, presence)
  |---- MinIO (binary objects)
  |---- Outbox Dispatcher
            |---- Neo4j projection
            |---- Milvus indexing
            |---- WebSocket event publication

Celery Workers
  |-- default queue
  |-- literature queue
  |-- embedding queue
  |-- agent queue
  |-- experiment queue / isolated runner
  |-- export queue
```

### 3.2 模块边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| Auth | 登录、令牌、密码、会话撤销 | 项目权限业务规则 |
| Teams | 团队、成员、团队角色 | 项目内容 |
| Projects | 项目、周期、成员、概览聚合 | 文献解析 |
| Lifecycle | 阶段状态机、门禁、推进、重开 | 具体实验执行 |
| Literature | 搜索、元数据、PDF 入库、解析、切片 | 研究结论批准 |
| Evidence | 证据节点、边、来源、图投影 | 文档编辑 |
| Experiments | 实验定义、运行、日志、指标、产物 | 任意宿主机代码执行 |
| Agents | 配置、任务编排、工具调用、记忆、预算 | 绕过权限直接改业务数据 |
| Writing | 文档、版本、引用、导出 | 生成无来源事实 |
| Assets | 对象元数据、签名上传、校验、版本清单 | 业务语义判定 |
| Approvals | 人工门禁、意见、批准/拒绝 | 自动替用户批准 |
| Audit | 不可变操作轨迹 | 业务状态更新 |

### 3.3 同步与异步边界

以下操作同步完成并在一次 PostgreSQL 事务内提交：普通 CRUD、权限检查、阶段轻量更新、评论、审批决定、证据节点/边编辑。以下操作必须返回 `202 Accepted` 和 Job：外部文献检索、PDF 解析、OCR、Embedding、批量证据抽取、Agent 运行、实验运行、文档导出、大图谱重建。

### 3.4 一致性规则

1. API 事务同时写业务表与 `outbox_events`。
2. Dispatcher 至少一次投递事件；消费者必须幂等。
3. Neo4j/Milvus 失败不回滚已提交的业务事实，但 UI 显示索引状态。
4. 每个投影记录包含 `source_version`，旧事件不得覆盖新状态。
5. 需要防止重复提交的写接口接受 `Idempotency-Key`。

---

## 4. 全局 UI 高保真实现规范

### 4.1 画布与布局

- 基准视口：`1440px × 900px`，浏览器缩放 100%。
- 全局页面背景：`#F6F8FB`。
- Dashboard 使用 `AppShell`：左侧固定导航 `220px`，右侧主区 `1220px`。
- Evidence Workspace 使用独立 `WorkspaceShell`：项目栏 `260px`、中央工作区 `860px`、右侧 Inspector `320px`；三栏合计 `1440px`。
- 主内容可纵向滚动，固定导航和 Header 不随主内容滚动。
- 在 `1280px–1439px` 宽度下，按可用宽度缩小卡片列宽但不改变信息顺序。
- 小于 `1280px` 时允许收起左栏；小于 `1024px` 时进入可读降级模式，不作为像素级验收基准。

### 4.2 CSS 设计令牌

```css
:root {
  --color-page: #F6F8FB;
  --color-surface: #FFFFFF;
  --color-surface-subtle: #F8FAFC;
  --color-primary: #165DFF;
  --color-primary-hover: #0F4DDB;
  --color-primary-soft: #EAF1FF;
  --color-brand-dark: #173B78;
  --color-nav-active: #164C9C;
  --color-text: #0F172A;
  --color-text-secondary: #475569;
  --color-text-muted: #64748B;
  --color-border: #E5E7EB;
  --color-border-strong: #CBD5E1;
  --color-success: #16A34A;
  --color-success-soft: #EAF8EF;
  --color-warning: #F59E0B;
  --color-warning-soft: #FFF7E6;
  --color-danger: #DC2626;
  --color-danger-soft: #FEECEC;
  --color-disabled: #94A3B8;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-card: 0 2px 8px rgba(15, 23, 42, 0.06);
  --shadow-popover: 0 12px 32px rgba(15, 23, 42, 0.14);
}
```

### 4.3 字体与排版

```css
font-family: Inter, "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
```

| 层级 | 字号/行高 | 字重 | 颜色 |
|---|---|---|---|
| 页面标题 | 32/40px | 700 | `#0F172A` |
| 区块标题 | 18/26px | 600 | `#0F172A` |
| 卡片主标题 | 20/28px | 600 | `#0F172A` |
| 正文 | 14/22px | 400 | `#334155` |
| 标签/表头 | 12/18px | 500/600 | `#64748B` |
| 代码/哈希 | 12/18px | 400 | `#334155`，等宽字体 |

数字必须使用等宽数字特性 `font-variant-numeric: tabular-nums`，防止状态刷新时抖动。

#### 4.3.1 图标与品牌图形

- 全站使用 Lucide，默认 `18 × 18px`、`stroke-width: 1.75`、`stroke-linecap: round`。
- Sidebar 依次使用：`LayoutDashboard`、`FolderOpen`、`BookOpen`、`FlaskConical`、`Database`、`Network`、`FileText`、`BrainCircuit`、`Bot`、`ClipboardCheck`、`Settings`；收起按钮使用 `PanelLeftClose`。
- 生命周期依次使用：`Lightbulb`、`BookOpen`、`GitBranch`、`FlaskConical`、`BadgeCheck`、`FilePenLine`、`RefreshCcw`、`Sparkles`，图标 `28 × 28px`。
- Header 使用 `Bell`、`CircleHelp`、`ChevronDown`；常规按钮图标 `16px`。
- 品牌图形在无原始 SVG 时使用确定性占位品牌标：`36 × 36px` 蓝色圆形，内部为白色三节点连线图形；不得使用 Emoji、随机 AI 图片或不同页面不同 Logo。
- 如果仓库获得原始设计 SVG，原始 SVG 覆盖上述品牌占位标，但其 Bounding Box 保持 `36 × 36px`。

### 4.4 间距、边框和卡片

- 间距基元：`4, 8, 12, 16, 20, 24, 32px`。
- 主内容外边距：`24px`。
- 同级卡片间距：`16px`。
- 卡片内边距：默认 `20px`，密集表格卡片可为 `16px`。
- 卡片：白色背景、`1px solid #E5E7EB`、`12px` 圆角、`var(--shadow-card)`。
- 表格行高：`52px` 或本文指定值；表头高 `40px`。
- 输入框高 `40px`；主要按钮高 `36px`；图标按钮 `36 × 36px`。

### 4.5 状态色语义

| 状态 | 颜色 |
|---|---|
| completed/succeeded/healthy | 绿色 `#16A34A` |
| running/active/selected | 蓝色 `#165DFF` |
| pending/queued/not_started | 灰色 `#94A3B8` |
| warning/waiting_approval | 黄色 `#F59E0B` |
| failed/blocked/unhealthy | 红色 `#DC2626` |

“锁定”若仅代表依赖未满足，使用灰色锁；若代表阻塞错误，使用红色并显示原因。不得把状态只编码为颜色，必须同时显示文字或图标。

### 4.6 全局交互状态

每个数据容器必须实现：

- 首次加载：与最终布局等尺寸的 Skeleton，不能造成大幅布局跳动。
- 刷新：保留旧数据并显示局部刷新标记。
- 空状态：解释为什么为空，并给有权限用户一个明确操作。
- 错误：显示可理解原因、`trace_id` 和重试按钮。
- 无权限：显示 403 专用状态，不伪装成数据为空。
- 删除/不可逆操作：二次确认；高风险动作要求输入资源名称或审批。
- 异步操作：立即显示 Job，支持进度、日志摘要、取消和失败重试。

### 4.7 可访问性

- 键盘可访问所有交互元素。
- 焦点环为 `2px #165DFF`，不能仅依赖浏览器不可见默认样式。
- 正文和背景对比度达到 WCAG 2.1 AA。
- 图表必须有文本摘要；图节点必须支持 Tab 选择和可访问名称。
- 图标按钮必须设置 `aria-label`；Tooltip 不能是唯一信息来源。

### 4.8 禁止事项

1. 禁止用 Ant Design 默认 Sidebar/Dashboard 视觉替代指定布局。
2. 禁止改动两张基准页面的信息顺序、卡片比例和三栏关系。
3. 禁止在生产模式生成随机业务数据。
4. 禁止只弹出“功能开发中”。
5. 禁止用前端本地状态假装审批、实验或 Agent 已在后台执行。
6. 禁止在图表和表格中硬编码当前项目的运行数据；示例数据只能位于明确的 seed 脚本。
7. 禁止把外部服务错误吞掉并返回成功。

---

## 5. 路由与全局导航

### 5.1 AppShell 路由

| 菜单 | 路由 | 必须提供的功能 |
|---|---|---|
| 研究总览 | `/projects/:projectId/overview` | 生命周期、项目概览、发现、趋势、审批、系统状态 |
| 项目空间 | `/projects` | 项目创建、搜索、归档、成员与周期管理 |
| 文献库 | `/projects/:projectId/literature` | 检索、上传、解析、筛选、阅读、证据提取 |
| 实验管理 | `/projects/:projectId/experiments` | 实验定义、运行、日志、指标、产物、比较 |
| 数据资产 | `/projects/:projectId/assets` | 数据集和文件版本、预览、哈希、权限 |
| 知识图谱 | `/projects/:projectId/knowledge-graph` | 全图查询、筛选、溯源、冲突查看 |
| 写作中心 | `/projects/:projectId/writing` | 文档编辑、引用、版本、导出 |
| 复盘洞察 | `/projects/:projectId/reflections` | 失败分析、经验、下一周期建议 |
| 智能体中心 | `/projects/:projectId/agents` | Agent 配置、任务、工具、预算、日志 |
| 审批中心 | `/projects/:projectId/approvals` | 待办、历史、批准、拒绝、评论 |
| 系统设置 | `/settings` | 用户、团队、连接器、模型、存储与安全设置 |

Evidence Workspace 使用 `/projects/:projectId/cycles/:cycleId/evidence`，进入后切换为 `WorkspaceShell`。

### 5.2 Sidebar 精确规格

- Bounding box：`x=0, y=0, width=220, height=900`。
- 背景 `#F8FAFC`；右边框 `1px #E5E7EB`。
- Logo 区：高 `90px`，左右内边距 `20px`。
- Logo 图形：`36 × 36px`，品牌名“研启智链”字号 `22px/30px`、字重 700、颜色 `#173B78`。
- 副标题：“AI-Researcher / 研究辅助中心”，`12px/18px`、颜色 `#64748B`。
- 菜单容器：`padding: 8px 12px`，允许独立纵向滚动。
- 菜单项：宽 `196px`、高 `44px`、圆角 `8px`、图标 `18px`、图标与文字间距 `12px`。
- 普通状态文字 `#475569`；Hover 背景 `#EEF2F7`；激活背景 `#164C9C`、文字和图标白色。
- 底部固定区包括“系统设置”和“收起导航”，上方 `1px` 分割线。
- 点击菜单必须路由到对应真实页面；当前项目 ID 由项目上下文提供。

### 5.3 Header 精确规格

- Bounding box：`x=220, y=0, width=1220, height=72`。
- 背景白色；底边 `1px #E5E7EB`。
- 左内边距 `24px`；页面标题垂直居中。
- 右侧从右向左：用户菜单、帮助、通知；间距 `12px`。
- 通知按钮显示真实未读数量；点击打开宽 `360px` 的通知 Popover。
- 用户头像 `32 × 32px`；用户菜单提供个人设置、团队切换和退出。

---

## 6. 研究总览 Dashboard 像素级规格

### 6.1 页面坐标

```text
Viewport: 1440 × 900
Sidebar: x=0,   y=0,  w=220,  h=900
Header:  x=220, y=0,  w=1220, h=72
Content: x=220, y=72, w=1220, min-h=828, padding=24
Inner content width: 1172
```

内容区按以下顺序排布：

```text
Lifecycle card      x=244 y=96  w=1172 h=150
16px vertical gap
Current project     x=244 y=262 w=578  h=296
Discovery card      x=838 y=262 w=578  h=296
16px vertical gap
Evidence trend      x=244 y=574 w=578  h=248
Approval card       x=838 y=574 w=578  h=248
System status bar   x=244 y=838 w=1172 h=38
```

若内容超出 900px，主内容区纵向滚动；上述坐标用于视觉回归基准，不得通过缩小字体强行塞入。

### 6.2 科研生命周期卡片

- 卡片高 `150px`，内边距 `16px 24px`。
- 标题“科研生命周期”位于左上，`16px/24px`、600。
- 节点区在标题下 `8px`，使用 `grid-template-columns: repeat(8, minmax(0, 1fr))`。
- 8 个单元依次为：选题、文献、假设、实验、验证、写作、复盘、进化。
- 每个节点视觉宽 `110px`，圆形状态图标 `64 × 64px`。
- 连接线位于圆心高度，`2px`，从前一单元中心延伸到后一单元中心；已完成区段绿色，未来区段 `#CBD5E1`。
- 名称在圆形下方 `8px`，字号 `14px`、600。
- 状态与辅助信息为 `12px/18px`。

默认 seed 展示：

| 阶段 | 状态 | 辅助信息 |
|---|---|---|
| 选题 | 已完成 | 候选 12 个 |
| 文献 | 已完成 | 证据 532 篇 |
| 假设 | 已完成 | 假设 4 个 |
| 实验 | 进行中 | 进度 62% |
| 验证 | 待开始 | 依赖实验 |
| 写作 | 待开始 | 尚未解锁 |
| 复盘 | 待开始 | 尚未解锁 |
| 进化 | 已锁定 | 等待复盘 |

交互：

- Hover 显示阶段起止时间、负责人、阻塞项、证据数。
- 点击节点进入该阶段对应页面并带 `stage` 查询参数。
- 只有具备权限的用户可从详情菜单启动、阻塞、完成或重开阶段。
- 完成阶段前调用服务端门禁校验；校验失败时展示缺失条件，不得在前端自行判定成功。
- 数据源：`GET /api/v1/projects/{project_id}/cycles/{cycle_id}/lifecycle`。

### 6.3 当前项目卡片

- Bounding box：`578 × 296px`；内边距 `20px`。
- 标题“当前项目”`18px/26px`、600。
- 项目名最多两行，`20px/28px`、600，超出用省略并在 Hover 显示全文。
- 进度区距项目名 `16px`；进度条可用宽度 `442px`、高 `8px`、圆角 `999px`；右侧百分比宽 `56px`。
- 下部使用两列信息区；字段名 `12px` 灰色，字段值 `14px` 深色。
- 右下主按钮“进入项目工作台”，点击进入 Evidence Workspace；次按钮“查看详情”进入项目设置。

显示字段：当前周期、当前阶段、下一步行动、负责人、文献证据数、实验运行数、数据集数、图表数。数据全部来自 `GET /api/v1/projects/{project_id}/dashboard`。

### 6.4 今日发现 / 本周选题卡片

- 标题栏高 `44px`，左侧标题，右侧“刷新发现”和“查看全部”。
- 表头高 `36px`；数据行高 `55px`；默认显示 3 行。
- 列宽：编号 `48px`、候选题 `250px`、来源数 `70px`、证据强度 `90px`、状态剩余宽度。
- 候选题单行省略，Hover 展示完整研究问题。
- 证据强度显示 0–100 分和微型进度条。
- 标签：高优先级为绿色、中优先级为黄色、探索中为灰色。

交互：

- “刷新发现”创建异步 Discovery Job：`POST /api/v1/projects/{project_id}/topic-discovery-runs`。
- 运行期间按钮变为进度状态，可进入 Job 抽屉查看检索源、命中数和失败源。
- 点击候选题打开详情抽屉，展示创新性、相似工作、证据来源、风险、Agent 推理摘要和“采纳为选题”。
- “采纳”必须记录用户、时间、候选版本，并更新当前周期的 topic 阶段。

### 6.5 研究证据覆盖趋势

- 标题栏包含周期选择器和“查看明细”。
- ECharts 绘图区尺寸约 `538 × 180px`。
- X 轴：`T-5, T-4, T-3, T-2, T-1, 当前`；Y 轴 `0–100%`。
- 默认 seed：`48, 55, 61, 67, 69, 62`。
- 折线 `#165DFF`、宽 `2px`；点直径 `7px`；面积填充从 `rgba(22,93,255,.16)` 渐变到透明。
- 网格线 `#E5E7EB`，只显示水平线。
- Tooltip 同时展示覆盖率、已验证主张数、未解决矛盾数。
- 数据源：`GET /api/v1/projects/{project_id}/evidence-coverage?cycles=6`。

覆盖率服务端计算公式：

```text
coverage = weighted_supported_claims / weighted_total_claims
```

权重来自 Claim 的重要级别；没有 Claim 时返回 `null`，UI 显示“尚无可计算主张”，不得显示 0% 误导用户。

### 6.6 待审批卡片

- 表头高 `36px`，数据行高 `52px`，默认展示 3 项。
- 列：事项、类型、提交人、提交时间、优先级、操作。
- 每行提供“查看”；具备审批权时同时显示“批准”“拒绝”。
- 批准/拒绝必须打开确认弹窗；拒绝必填原因。
- 更新成功后以 TanStack Query 精确失效审批和生命周期缓存。
- 数据源：`GET /api/v1/projects/{project_id}/approvals?status=pending&limit=3`。

### 6.7 底部系统状态条

- 高 `38px`，白色卡片，横向显示：Agent 服务、数据服务、对象存储、GPU 资源、最近备份。
- 绿色/黄/红状态点直径 `8px`；每项可点击打开详情。
- 示例：“智能体服务 6/6 正常”“数据服务 正常”“存储空间 2.1TB”“GPU 资源 2/4 空闲”。
- 数据源：`GET /api/v1/system/health/summary`；健康信息不得由前端猜测。

### 6.8 Dashboard 聚合响应示例

```json
{
  "project": {
    "id": "project_uuid",
    "name": "基于多模态表征学习的蛋白质-小分子相互作用预测",
    "current_cycle_id": "cycle_uuid",
    "current_stage": "experiment",
    "progress_percent": 62,
    "next_action": "完成实验组 S3 Docking 评估并汇总结果",
    "owner": {"id": "user_uuid", "name": "李研究员"}
  },
  "statistics": {
    "papers": 532,
    "experiment_runs": 28,
    "datasets": 3,
    "figures": 14
  },
  "updated_at": "2026-08-16T06:00:00Z"
}
```

---

## 7. Evidence Workspace 像素级规格

### 7.1 整体三栏布局

```text
Viewport 1440 × 900
Project Explorer: x=0,    y=0, w=260, h=900
Main Workspace:   x=260,  y=0, w=860, h=900
Inspector:        x=1120, y=0, w=320, h=900
```

三栏分别滚动，不能让 Inspector 被中央内容挤出视口。左右栏为白色，中央为 `#F6F8FB`。左右分隔线均为 `1px #E5E7EB`。

### 7.2 左侧 Project Explorer

- 顶部品牌/返回区高 `64px`，包含返回研究总览按钮和当前 Team。
- 搜索框位于 `x=16, y=80, w=228, h=40`，提示“搜索项目或周期”。
- 项目列表起始 `y=136`；条目宽 `228px`、最小高 `70px`、圆角 `8px`、间距 `8px`。
- 条目显示项目名、周期编号、更新时间和状态点。
- 选中项背景 `#EAF1FF`，左侧 `3px #165DFF`；普通 Hover 背景 `#F8FAFC`。
- 项目可展开显示周期，点击周期更新 URL 中 `cycleId` 并加载对应证据图。
- 底部提供“新建项目”和用户入口；新建项目打开真实创建表单。

### 7.3 中央 Header

- 高 `88px`，白色，内边距 `16px 24px`，底边 `1px #E5E7EB`。
- 第一行标题“项目工作台”`24px/32px`、700。
- 第二行显示完整项目名称，`14px`、颜色 `#475569`。
- 右侧依次为当前日期、刷新按钮、更多菜单。
- 刷新只刷新当前周期聚合数据，不重新启动 Agent。

### 7.4 Evidence Graph

- 外部容器：`margin: 16px 24px 0`，宽 `812px`、高 `300px`，白色卡片。
- 卡片标题“科研证据链”，右侧提供节点类型筛选、缩放复位和全屏。
- React Flow 世界坐标最小尺寸 `1160 × 260px`；初次加载 `fitView`，`fitViewOptions.padding=0.12`，`minZoom=0.65`，`maxZoom=1.5`。
- 默认 6 个主节点尺寸 `150 × 180px`，坐标如下：

| 节点 | 类型 | x | y |
|---|---|---:|---:|
| RQ1 | ResearchQuestion | 40 | 40 |
| P1 | Paper | 220 | 40 |
| H1 | Hypothesis | 400 | 40 |
| E1 | Experiment | 580 | 40 |
| V1 | Validation | 760 | 40 |
| C1 | Claim | 940 | 40 |

节点样式：白色背景、`1px #CBD5E1`、`12px` 圆角、内边距 `12px`。选中节点边框 `2px #165DFF` 并使用蓝色柔光。节点顶部显示编号和类型标签，中部显示最多 5 行描述，底部显示证据数量、置信度或运行状态。

主链边使用 `#94A3B8`、`2px`、闭合箭头；支持关系用绿色、反驳关系用红色虚线、来源关系用灰色。边必须有可见关系标签。节点与边均来自后端，不允许前端从展示文本推断关系。

交互：

- 单击节点：URL 写入 `?node=<id>`，右侧 Inspector 加载详情。
- 双击节点：打开全屏详情页。
- 拖动节点：仅保存 `layout_x/layout_y`，不改变学术关系。
- 新建边：先打开关系类型与来源确认弹窗，再调用 API。
- 删除节点/边：需要权限和确认；被文档主张引用的节点不可直接硬删除，只能归档。
- 多选后可批量打标签，但不得批量自动改变支持/反驳关系。

### 7.5 项目执行时间线

- 位于证据图下方，`margin: 16px 24px 0`，卡片宽 `812px`、高 `92px`。
- 阶段：问题定义、文献证据、假设构建、实验设计、实验执行、验证分析、论文撰写。
- 已完成显示绿色勾，当前显示蓝色圆点和脉冲环，未来显示灰色圆点，阻塞显示红色叹号。
- 点击阶段滚动或路由到对应工作区。

### 7.6 下一步行动卡

- `margin: 16px 24px 0`，宽 `812px`、最小高 `100px`。
- 背景 `#FFF7E6`，边框 `#FDE7B2`。
- 左侧显示“下一步行动”和建议完成时间，下面显示可执行任务、来源及生成者。
- 右侧按钮“标记完成”；点击后需填写完成说明或关联证据，不允许只有本地勾选。
- 若行动由 Agent 生成，显示 Agent 名称、任务 ID 和生成时间。

### 7.7 发现与候选证据表

- 位于行动卡下方，宽 `812px`，允许随中央列纵向滚动。
- Tab：“今日发现”“本周候选证据”。
- 列：标题、来源、类型、证据倾向、相关节点、操作。
- 每行必须提供“查看来源”“关联节点”；来源不可访问时显示原因。
- 证据倾向只能是 `supports`、`contradicts`、`neutral`、`uncertain`，并同时显示文字。

### 7.8 右侧 Evidence Inspector

- 宽 `320px`，背景白色，内边距 `16px`。
- 顶部高 `56px`，标题“节点详情”，右侧关闭/更多按钮。
- 无选中节点时显示引导空状态；有节点时按以下顺序展示：

1. 节点编号、类型、状态和置信度。
2. 完整描述及编辑入口。
3. “文献证据 N 篇”列表：Checkbox、论文标题、年份、来源。
4. 关联实验/结果。
5. 源文件卡：PDF 图标、文件名、对象路径、大小、下载/复制链接。
6. SHA-256：灰色等宽代码框，支持复制。
7. Provenance：抽取方式、页码/段落、Agent 或用户、时间。
8. 评论/标注列表及新增输入框。

勾选文献只改变当前节点的证据关联；必须调用 API 并支持失败回滚。下载使用短期签名 URL。Hash 来自服务端入库校验，禁止在浏览器用文件名伪造。

### 7.9 Workspace 所需接口

```text
GET    /api/v1/projects/{project_id}/cycles
GET    /api/v1/projects/{project_id}/cycles/{cycle_id}/workspace
GET    /api/v1/projects/{project_id}/cycles/{cycle_id}/evidence-graph
POST   /api/v1/projects/{project_id}/evidence/nodes
GET    /api/v1/projects/{project_id}/evidence/nodes/{node_id}
PATCH  /api/v1/projects/{project_id}/evidence/nodes/{node_id}
DELETE /api/v1/projects/{project_id}/evidence/nodes/{node_id}
POST   /api/v1/projects/{project_id}/evidence/edges
PATCH  /api/v1/projects/{project_id}/evidence/edges/{edge_id}
DELETE /api/v1/projects/{project_id}/evidence/edges/{edge_id}
PUT    /api/v1/projects/{project_id}/evidence/layout
POST   /api/v1/projects/{project_id}/evidence/nodes/{node_id}/sources
DELETE /api/v1/projects/{project_id}/evidence/nodes/{node_id}/sources/{source_id}
POST   /api/v1/projects/{project_id}/evidence/nodes/{node_id}/comments
GET    /api/v1/projects/{project_id}/knowledge-graph
GET    /api/v1/projects/{project_id}/knowledge-graph/nodes/{node_id}/neighbors
```

Knowledge Graph 查询端点只返回有权限的子图，并强制 `depth <= 3`、节点上限和查询超时；所有写操作仍通过 Evidence Node/Edge API。

---
## 8. 其余功能页面规格

两张参考图只定义 Dashboard 与 Evidence Workspace 的像素级基准。其余页面必须复用同一设计令牌、Sidebar、Header、卡片、表格、状态和交互模式，不得退化为无样式 CRUD 页面。

### 8.1 项目空间

必须支持：

- 按名称、负责人、阶段、状态、更新时间筛选项目。
- 创建项目：名称、研究领域、研究目标、团队、可见性、默认语言。
- 项目详情：描述、成员、当前周期、里程碑、标签、归档状态。
- 新建研究周期：从空白创建或从上一周期复制已批准配置，不能复制运行状态。
- 成员管理与项目角色分配。
- 归档与恢复；物理删除仅 Owner 可发起并经过审批/延迟删除。

项目卡所有统计来自聚合 API。创建成功后必须进入新项目，不能只在本地列表追加。

### 8.2 文献库

布局：顶部搜索与连接器区、左侧筛选栏、中央论文列表、右侧详情抽屉。必须支持：

- 关键词、作者、标题、DOI、年份、来源、标签、解析状态搜索。
- Semantic Scholar、PubMed、arXiv、Crossref 适配器；单源失败不应吞掉其他源结果。
- PDF 拖放上传、批量上传、进度、取消、重复检测、恶意文件扫描状态。
- 元数据纠错、作者、摘要、引用信息、原始来源链接。
- PDF 在线预览，并能定位证据页码/段落。
- 解析、OCR、Chunk、Embedding、证据抽取的逐阶段状态。
- 加入/移出研究周期、收藏、标签、批量重试解析。
- 相似论文、引用/被引关系和去重合并建议。

外部检索结果只有在用户收藏、加入项目或 Agent 选择后才持久化为 Project Paper；全局 Paper 元数据可去重共享，但项目标签、备注和权限必须隔离。

### 8.3 实验管理

必须提供实验列表、实验定义页、运行详情页和运行对比页：

- 创建实验：目标、入口命令、代码快照、容器镜像、数据集版本、参数、环境变量白名单、CPU/GPU/内存/超时。
- 运行：排队、取消、重试、克隆参数、停止。
- 实时日志：WebSocket/SSE 增量加载、关键字搜索、下载归档。
- 指标：时间序列、最终指标、不同运行对比。
- 产物：模型、Checkpoint、图表、报告和任意声明输出，均保存 Hash。
- 复现：固定代码 commit 或内容 Hash、镜像 digest、依赖、随机种子、数据集版本和参数。
- 结果分析：Agent 只能基于运行产物生成结构化分析，必须关联来源。

V1 运行器只允许预批准镜像或项目构建镜像；禁止特权容器、宿主网络和任意宿主目录挂载。

### 8.4 数据资产

实现 Mini-DVC 风格的数据资产管理：

- Dataset、Dataset Version、文件清单、Schema、统计摘要、许可证、数据来源。
- 通过签名 URL 分片上传；服务端完成大小、MIME、SHA-256 校验。
- 版本不可原地修改；修改创建新版本。
- 支持 CSV/TSV/JSON/Parquet 的受限预览，默认最多 100 行。
- 敏感字段标签与下载权限。
- 数据集被实验引用后不可硬删除；只能废弃并保留可复现性。

### 8.5 知识图谱

知识图谱页展示一个项目或多个周期的完整关系投影，支持：

- 节点类型、关系、周期、时间、置信度、来源、标签筛选。
- 搜索并定位节点；查看一至三跳邻居。
- 支持/反驳关系聚合；孤立节点和未解决矛盾列表。
- 从 Neo4j 查询，但所有编辑命令回到 Evidence API 和 PostgreSQL。
- 投影延迟时显示 `indexing` 状态和最新同步版本。

### 8.6 写作中心

必须提供结构化文档树、Markdown/富文本编辑区、引用/证据侧栏和版本历史：

- 文档结构：Title、Abstract、Introduction、Related Work、Method、Results、Discussion、Conclusion、References，可由用户增减。
- Claim 必须关联至少一个 Evidence Node，或明确标记“待补证据”。
- 引用插入、去重、样式选择、缺失字段警告。
- Agent 生成内容以建议 Diff 形式出现，用户接受后才写入正式版本。
- 每次保存创建可追踪版本或增量快照；支持版本比较和恢复。
- 异步导出 Markdown、LaTeX、DOCX、PDF；失败提供编译日志。
- 导出前执行引用完整性、未支持主张、图表缺失、Hash 缺失检查。

### 8.7 复盘洞察

Reflection Agent 必须生成结构化内容：达成/未达成目标、失败假设、异常实验、证据缺口、资源消耗、可复用经验、下一周期建议。每条结论要关联证据、实验或任务。用户可批准某条建议并一键创建下一周期的候选任务；未经批准不得自动改变项目方向。

### 8.8 智能体中心

必须支持：

- Agent 列表、版本、启停状态、模型 Provider、工具白名单、预算、最近运行。
- 任务队列：queued、running、waiting_approval、succeeded、failed、cancelled。
- 任务详情：输入、计划步骤、工具调用、结构化输出、Token/费用/耗时、日志、引用、错误。
- 取消、重试、从失败步骤恢复；重试创建新 attempt，不覆盖旧日志。
- Prompt/配置版本回溯；密钥只显示已配置状态，绝不回显明文。

### 8.9 审批中心

审批类型至少包括：阶段完成、采纳选题、发布主张、运行高资源实验、使用外部写权限工具、删除资产、导出敏感数据。审批对象必须记录请求前状态快照、请求人、原因、风险、过期时间。批准和拒绝均不可修改，只能通过新审批纠正。

### 8.10 系统设置

包括个人资料、团队成员、连接器状态、模型 Provider、Embedding/OCR Provider、对象存储、实验执行器、通知策略、API Key、审计导出。连接测试必须真实调用最小健康检查，并隐藏敏感值。

---

## 9. 前端工程架构

### 9.1 目录结构

```text
frontend/
  src/
    app/
      App.tsx
      router.tsx
      providers.tsx
      queryClient.ts
    api/
      client.ts
      generated/
      errors.ts
      websocket.ts
    components/
      common/
      feedback/
      forms/
      layout/
    features/
      auth/
      projects/
      dashboard/
      lifecycle/
      literature/
      evidence/
      experiments/
      assets/
      agents/
      writing/
      approvals/
      settings/
    pages/
      DashboardPage.tsx
      EvidenceWorkspacePage.tsx
      LiteraturePage.tsx
      ExperimentsPage.tsx
      AssetsPage.tsx
      KnowledgeGraphPage.tsx
      WritingPage.tsx
      ReflectionsPage.tsx
      AgentsPage.tsx
      ApprovalsPage.tsx
      SettingsPage.tsx
    stores/
      authStore.ts
      uiStore.ts
      workspaceStore.ts
    styles/
      tokens.css
      globals.css
      ant-theme.ts
    types/
    utils/
    test/
```

每个 `features/<domain>` 只包含该域的组件、hooks、schema 和 API 包装。跨域复用组件必须移动到 `components/common`；不要创建一个包含整个平台状态的巨型 Store。

### 9.2 组件树

```text
App
  AuthProvider
  TeamProvider
  QueryClientProvider
  Router
    AppShell
      Sidebar
      Header
      Outlet
        DashboardPage
          LifecycleTimeline
          CurrentProjectCard
          DiscoveryTable
          EvidenceCoverageChart
          ApprovalTable
          SystemStatusBar
    WorkspaceShell
      ProjectExplorer
      EvidenceWorkspacePage
        WorkspaceHeader
        EvidenceGraph
        ResearchStageTimeline
        NextActionCard
        CandidateEvidenceTable
      EvidenceInspector
```

### 9.3 状态管理原则

- TanStack Query 管理所有服务端状态；Query Key 必须包含 `teamId/projectId/cycleId`。
- Zustand 只管理 Sidebar 收起、Inspector 开关、React Flow 视口、用户未提交的 UI 选择等短期状态。
- URL 管理可分享状态：当前项目、周期、Tab、筛选、选中证据节点。
- 表单草稿使用 React Hook Form；需要长期草稿时调用后端 Draft API。
- 禁止把 API 数据复制到 Zustand 后再双向同步。

建议 Query Key：

```ts
['project', projectId]
['dashboard', projectId, cycleId]
['lifecycle', projectId, cycleId]
['evidence-graph', projectId, cycleId, filters]
['evidence-node', projectId, nodeId]
['agent-task', projectId, taskId]
```

### 9.4 API Client

- 从 OpenAPI 生成基础 TypeScript 类型和调用器；可在其上封装领域 Hook，但不得手写重复 DTO。
- 所有请求附带 `Authorization`、`X-Request-ID`；写请求按需附带 `Idempotency-Key` 和 `If-Match`。
- 401 时最多自动刷新一次 Token；刷新失败清除会话并跳转登录。
- 429 尊重 `Retry-After`；不得无限自动重试。
- 4xx 业务错误不自动重试；网络错误和 5xx 的只读请求最多指数退避重试 2 次。
- API 错误统一转换为 `AppError`，保留 `code/message/field_errors/trace_id`。

### 9.5 乐观更新与并发

只有低风险、可安全回滚的操作可乐观更新，如标签、图节点位置、普通评论。审批、阶段推进、实验启动、Agent 启动、删除和权限变更必须等待服务端确认。可编辑资源返回 `version` 和 ETag；冲突返回 409，UI 提供刷新/比较，不得静默覆盖。

### 9.6 实时事件

前端连接：

```text
WS /api/v1/ws/projects/{project_id}?token=<short_lived_ws_token>
```

事件用于 Job 进度、Agent 状态、实验日志指针、审批数量和索引状态。WebSocket 断线后指数退避重连，并用最后事件序号调用 REST 补齐；不能把 WebSocket 作为唯一数据源。

### 9.7 上传流程

```text
1. POST /assets/uploads:initiate -> upload_id + presigned parts
2. Browser direct upload to MinIO
3. POST /assets/uploads/{upload_id}:complete with part etags
4. Server verifies size/hash/mime and creates Asset
5. Optional parsing/indexing Job starts
```

UI 必须支持进度、暂停/取消、失败分片重试和重复 Hash 提示。签名 URL 不写日志、不持久化到业务表。

### 9.8 前端错误边界

- 路由级 Error Boundary 防止单页错误破坏整个应用。
- Evidence Graph 和 ECharts 单独 Error Boundary。
- Error 页面显示用户可理解的信息、重试、返回路径和 `trace_id`。
- 捕获到的错误上报时移除 Token、签名 URL、文献全文和敏感输入。

### 9.9 前端性能基线

- 路由级按需加载。
- 大表格虚拟化；超过 100 行不得一次渲染全部 DOM。
- Evidence Graph 超过 500 节点默认聚类，超过 2,000 节点必须服务端分页/子图查询。
- PDF、图谱和编辑器不进入首页主包。
- Dashboard 在本地标准数据集下 LCP 小于 2.5 秒，交互后 100ms 内提供视觉反馈。

---

## 10. 后端工程架构

### 10.1 目录结构

```text
backend/
  app/
    main.py
    api/
      deps.py
      errors.py
      v1/
        router.py
        auth.py
        projects.py
        lifecycle.py
        literature.py
        evidence.py
        experiments.py
        assets.py
        agents.py
        writing.py
        approvals.py
        system.py
    core/
      config.py
      security.py
      logging.py
      telemetry.py
      idempotency.py
    db/
      base.py
      session.py
      models/
      migrations/
    domains/
      auth/
      teams/
      projects/
      lifecycle/
      literature/
      evidence/
      experiments/
      assets/
      agents/
      writing/
      approvals/
      audit/
    integrations/
      llm/
      embeddings/
      literature_sources/
      ocr/
      object_storage/
      graph/
      vector_store/
      experiment_runner/
    workers/
      celery_app.py
      tasks/
    events/
      outbox.py
      dispatcher.py
      consumers.py
    tests/
```

每个领域包含 `models.py`、`schemas.py`、`repository.py`、`service.py` 和必要的 `policies.py`。API 路由只做解析、依赖注入、调用 Service 和格式化响应；禁止把业务状态机写在路由函数内。

### 10.2 请求处理顺序

```text
Request ID
 -> authentication
 -> team/project context resolution
 -> authorization policy
 -> schema validation
 -> domain service
 -> PostgreSQL transaction + audit + outbox
 -> response envelope
```

每个请求和异步任务必须传播 `trace_id`、`actor_id`、`team_id`、`project_id`。异步任务中的 actor 是发起用户，系统任务另记 `system_actor`。

### 10.3 Repository 与事务

- Repository 只执行数据读写，不包含跨对象业务规则。
- Service 控制事务和状态转换。
- 同一请求使用一个 Unit of Work。
- 审计记录和 Outbox 事件与业务写入同事务提交。
- 所有列表接口在数据库层分页和过滤。
- 防止 N+1 查询；Dashboard 使用明确聚合查询或短期缓存。

### 10.4 异步任务队列

| Queue | 任务 | 并发原则 |
|---|---|---|
| `default` | 通知、轻量聚合、Outbox | 高并发 |
| `literature` | 外部检索、PDF 解析、OCR | 按连接器限流 |
| `embedding` | Chunk Embedding、Milvus 写入 | 批处理 |
| `agent` | Agent 编排和工具调用 | 按项目/预算限流 |
| `experiment` | 容器实验执行 | 按 CPU/GPU 资源调度 |
| `export` | LaTeX/DOCX/PDF 导出 | 中低并发 |

任务必须具备：幂等键、最大尝试次数、指数退避、可取消检查点、进度、结构化错误和 Dead Letter 状态。长任务不得只依赖 Celery result backend；业务状态写入 `jobs`/领域任务表。

### 10.5 缓存

- Dashboard 聚合可缓存 30 秒，Key 必须包含项目和周期。
- 权限和用户会话变更后立即失效相关缓存。
- 外部检索查询可按归一化 Query 缓存 10 分钟，但不同团队的私有过滤条件不可共享。
- Redis 不可存放唯一副本、完整论文正文或长期 Agent Memory。

### 10.6 外部集成适配器

每个适配器实现统一能力检测、超时、限流、重试和错误映射。例如 Literature Provider：

```python
class LiteratureProvider(Protocol):
    async def search(self, query: SearchQuery) -> SearchPage: ...
    async def fetch_metadata(self, external_id: str) -> PaperMetadata: ...
    async def fetch_citations(self, external_id: str) -> CitationPage: ...
```

不得让领域 Service 依赖某个外部 Provider 的私有响应结构。

### 10.7 健康检查

- `/health/live`：进程存活，不访问外部依赖。
- `/health/ready`：PostgreSQL、Redis 和必要配置可用。
- `/api/v1/system/health/summary`：按权限返回服务、Worker、存储、索引和 GPU 摘要。
- 外部 LLM/论文源故障不应让核心 API readiness 失败，但必须显示 degraded。

---

## 11. PostgreSQL 数据库设计

### 11.1 通用约定

- 主键统一 `UUID`，默认 `gen_random_uuid()`。
- 时间统一 `TIMESTAMPTZ`，数据库保存 UTC，前端按用户时区显示。
- 用户可编辑实体包含 `created_at`、`updated_at`、`created_by`、`updated_by`、`version INT`。
- 需要保留历史的实体采用 `archived_at` 或 `deleted_at` 软删除；实验运行、审批决定、审计日志和文档版本禁止原地覆盖。
- 业务枚举使用 PostgreSQL Enum 或带 `CHECK` 的文本；不得散落任意字符串。
- 结构化、稳定、需要查询的字段必须建列；只有 Provider 原始响应、参数和扩展元数据使用 `JSONB`。
- 所有外键明确 `ON DELETE` 行为。被复现链路引用的数据默认 `RESTRICT` 或软删除。
- 每个 Team 范围表必须可由 `team_id` 直接或通过项目关联定位，以执行租户隔离。

### 11.2 核心枚举

```text
project_status       = active | paused | archived
cycle_status         = draft | active | completed | archived
lifecycle_stage_key  = topic | literature | hypothesis | experiment | validation | writing | reflection | evolution
stage_status         = pending | ready | running | waiting_approval | blocked | completed | failed | cancelled
job_status           = queued | running | waiting_approval | succeeded | failed | cancelled
experiment_run_status= queued | preparing | running | uploading_artifacts | succeeded | failed | cancelled
action_status        = open | in_progress | completed | cancelled
evidence_node_type   = research_question | paper | evidence | hypothesis | experiment | result | validation | claim | dataset | method
evidence_relation    = supports | contradicts | derived_from | cites | uses | tested_by | validated_by | produces | related_to
evidence_stance      = supports | contradicts | neutral | uncertain
approval_status      = pending | approved | rejected | cancelled | expired
asset_kind           = pdf | dataset_file | code | log | checkpoint | model | figure | report | export | other
parse_status         = pending | parsing | parsed | needs_ocr | failed
```

### 11.3 身份、团队和项目

#### `users`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | UUID PK | 用户 ID |
| `email` | CITEXT UNIQUE NOT NULL | 登录邮箱 |
| `password_hash` | TEXT NULL | OIDC-only 用户可为空 |
| `display_name` | VARCHAR(120) NOT NULL | 显示名 |
| `avatar_url` | TEXT NULL | 头像地址或受控资源地址 |
| `locale` | VARCHAR(16) DEFAULT `zh-CN` | 语言 |
| `timezone` | VARCHAR(64) DEFAULT `Asia/Shanghai` | IANA 时区 |
| `status` | VARCHAR(20) CHECK | active/disabled |
| `last_login_at` | TIMESTAMPTZ NULL | 最近登录 |
| `created_at`,`updated_at` | TIMESTAMPTZ | 时间 |

索引：唯一 `lower(email)`；`status`。

#### `refresh_sessions`

`id UUID PK, user_id UUID FK, token_hash TEXT UNIQUE, family_id UUID, expires_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ NULL, replaced_by UUID NULL, ip_hash TEXT NULL, user_agent TEXT NULL, created_at TIMESTAMPTZ`。只保存 Refresh Token Hash；检测到旧 Token 重放时撤销整个 family。

#### `teams`

`id UUID PK, name VARCHAR(160), slug CITEXT UNIQUE, owner_user_id UUID FK users, status VARCHAR(20), settings JSONB, created_at, updated_at`。

#### `team_members`

`team_id UUID FK, user_id UUID FK, role VARCHAR(20), joined_at TIMESTAMPTZ, invited_by UUID NULL, PRIMARY KEY(team_id,user_id)`。索引：`(user_id, team_id)`。

#### `projects`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | UUID PK | 项目 ID |
| `team_id` | UUID FK teams NOT NULL | 隔离边界 |
| `name` | VARCHAR(240) NOT NULL | 项目名 |
| `slug` | CITEXT NOT NULL | 团队内唯一 |
| `description` | TEXT | 描述 |
| `research_domain` | VARCHAR(120) | 研究领域 |
| `objective` | TEXT | 总目标 |
| `status` | project_status | 状态 |
| `current_cycle_id` | UUID NULL | 当前周期，延迟 FK |
| `visibility` | VARCHAR(20) | private/team |
| `created_by` | UUID FK users | 创建人 |
| `created_at`,`updated_at`,`archived_at` | TIMESTAMPTZ | 时间 |
| `version` | INT DEFAULT 1 | 乐观锁 |

约束与索引：`UNIQUE(team_id, slug)`；`(team_id,status,updated_at DESC)`；`current_cycle_id` 必须属于本项目。

#### `project_members`

`project_id UUID FK, user_id UUID FK, role VARCHAR(20), permissions_override JSONB NULL, created_at, PRIMARY KEY(project_id,user_id)`。

#### `research_cycles`

`id UUID PK, project_id UUID FK, sequence_no INT, name VARCHAR(160), objective TEXT, status cycle_status, started_at TIMESTAMPTZ NULL, completed_at TIMESTAMPTZ NULL, based_on_cycle_id UUID NULL, created_by UUID, created_at, updated_at, version INT`。

约束：`UNIQUE(project_id,sequence_no)`；同一项目最多一个 `active` 周期（部分唯一索引）。

#### `lifecycle_stages`

`id UUID PK, cycle_id UUID FK, stage_key lifecycle_stage_key, ordinal SMALLINT, status stage_status, progress NUMERIC(5,2), owner_user_id UUID NULL, started_at TIMESTAMPTZ NULL, completed_at TIMESTAMPTZ NULL, blocked_reason TEXT NULL, gate_snapshot JSONB, evidence_count INT DEFAULT 0, version INT DEFAULT 1, created_at, updated_at`。

约束：`UNIQUE(cycle_id,stage_key)`、`UNIQUE(cycle_id,ordinal)`、`progress BETWEEN 0 AND 100`。索引：`(cycle_id,ordinal)`、`(owner_user_id,status)`。

#### `stage_transition_events`

`id UUID PK, stage_id UUID FK, from_status stage_status, to_status stage_status, reason TEXT NULL, gate_result JSONB, actor_user_id UUID NULL, agent_task_id UUID NULL, created_at TIMESTAMPTZ`。只追加，不更新。

#### `research_actions`

`id UUID PK, project_id UUID FK, cycle_id UUID FK, stage_key lifecycle_stage_key NULL, title VARCHAR(240), description TEXT, status action_status, priority SMALLINT DEFAULT 3, due_at TIMESTAMPTZ NULL, assignee_user_id UUID NULL, source_type VARCHAR(20), source_agent_task_id UUID NULL, evidence_refs JSONB, completed_by UUID NULL, completed_at TIMESTAMPTZ NULL, completion_note TEXT NULL, version INT DEFAULT 1, created_at, updated_at`。

Dashboard 与 Workspace 的“下一步行动”取当前周期最高优先级且未完成的 Action；标记完成必须写完成说明或关联证据。索引：`(cycle_id,status,priority,due_at)`。

### 11.4 选题与文献

#### `topic_discovery_runs`

`id UUID PK, project_id UUID FK, cycle_id UUID FK, query JSONB, providers JSONB, status job_status, progress NUMERIC(5,2), result_summary JSONB, error JSONB NULL, requested_by UUID, started_at, finished_at, created_at`。

#### `topic_candidates`

`id UUID PK, discovery_run_id UUID FK, project_id UUID FK, cycle_id UUID FK, title TEXT, research_question TEXT, rationale TEXT, novelty_score NUMERIC(5,2), evidence_strength NUMERIC(5,2), risk_score NUMERIC(5,2), status VARCHAR(24), similar_work_summary TEXT, version INT, created_at, updated_at, accepted_at TIMESTAMPTZ NULL, accepted_by UUID NULL`。

索引：`(project_id,cycle_id,status,novelty_score DESC)`。

#### `topic_candidate_sources`

`candidate_id UUID FK, paper_id UUID FK, stance evidence_stance, relevance NUMERIC(5,2), reason TEXT, PRIMARY KEY(candidate_id,paper_id)`。

#### `literature_search_runs`

`id UUID PK, project_id UUID FK, cycle_id UUID NULL, normalized_query TEXT, raw_query JSONB, providers JSONB, status job_status, provider_results JSONB, result_count INT, error JSONB NULL, requested_by UUID, created_at, finished_at`。

#### `papers`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | UUID PK | 全局论文实体 |
| `doi` | CITEXT NULL | 归一化 DOI |
| `title` | TEXT NOT NULL | 标题 |
| `abstract` | TEXT NULL | 摘要 |
| `publication_year` | SMALLINT NULL | 年份 |
| `venue` | TEXT NULL | 期刊/会议 |
| `publication_date` | DATE NULL | 日期 |
| `external_ids` | JSONB | PubMed/arXiv/S2 等 ID |
| `citation_count` | INT NULL | 带采集时间的外部快照 |
| `metadata_source` | VARCHAR(40) | 主元数据源 |
| `raw_metadata` | JSONB | 原始响应 |
| `created_at`,`updated_at` | TIMESTAMPTZ | 时间 |

唯一策略：有 DOI 时唯一 `lower(doi)`；无 DOI 时使用 `normalized_title + year + first_author` 的去重候选，不自动合并低置信记录。

#### `authors` 与 `paper_authors`

- `authors(id UUID PK, name TEXT, orcid CITEXT NULL UNIQUE, affiliations JSONB, created_at, updated_at)`。
- `paper_authors(paper_id UUID FK, author_id UUID FK, ordinal SMALLINT, is_corresponding BOOL, PRIMARY KEY(paper_id,author_id), UNIQUE(paper_id,ordinal))`。

#### `project_papers`

`id UUID PK, project_id UUID FK, paper_id UUID FK, status VARCHAR(24), tags TEXT[], notes TEXT NULL, added_by UUID, added_at, archived_at NULL, UNIQUE(project_id,paper_id)`。项目私有注释不得写入全局 `papers`。

#### `cycle_papers`

`cycle_id UUID FK, project_paper_id UUID FK, inclusion_status VARCHAR(24), relevance NUMERIC(5,2) NULL, added_by UUID, added_at TIMESTAMPTZ, PRIMARY KEY(cycle_id,project_paper_id)`。同一项目论文可被多个研究周期复用，且每个周期保留独立纳排状态。

#### `paper_files`

`id UUID PK, project_paper_id UUID FK, asset_id UUID FK, file_role VARCHAR(20), parse_status parse_status, page_count INT NULL, parser_version VARCHAR(40) NULL, language VARCHAR(16) NULL, error JSONB NULL, created_at, updated_at`。

#### `paper_chunks`

`id UUID PK, paper_file_id UUID FK, chunk_index INT, page_start INT NULL, page_end INT NULL, section_path TEXT[] NULL, content TEXT, content_hash CHAR(64), token_count INT, embedding_model VARCHAR(120) NULL, vector_ref VARCHAR(160) NULL, embedding_status VARCHAR(20), created_at`。

约束：`UNIQUE(paper_file_id,chunk_index)`；索引：`(paper_file_id,page_start)`、`content_hash`。全文检索可对 `content` 建 GIN `tsvector` 索引。

### 11.5 证据图

#### `evidence_nodes`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | UUID PK | 节点 ID |
| `project_id`,`cycle_id` | UUID FK | 所属范围 |
| `node_type` | evidence_node_type | 类型 |
| `code` | VARCHAR(32) | 如 RQ1/H1/E1 |
| `title` | TEXT | 标题 |
| `description` | TEXT | 描述 |
| `status` | VARCHAR(24) | draft/active/validated/archived |
| `confidence` | NUMERIC(5,2) NULL | 0–100 |
| `importance` | SMALLINT DEFAULT 1 | 1–5 |
| `metadata` | JSONB | 类型扩展字段 |
| `created_by`,`updated_by` | UUID | 操作者 |
| `agent_task_id` | UUID NULL | 若由 Agent 创建 |
| `version` | INT | 乐观锁 |
| `created_at`,`updated_at`,`archived_at` | TIMESTAMPTZ | 时间 |

约束：`UNIQUE(cycle_id,code)`；`confidence IS NULL OR confidence BETWEEN 0 AND 100`。索引：`(project_id,cycle_id,node_type,status)`。

#### `evidence_edges`

`id UUID PK, project_id UUID FK, cycle_id UUID FK, source_node_id UUID FK, target_node_id UUID FK, relation evidence_relation, stance evidence_stance NULL, confidence NUMERIC(5,2) NULL, rationale TEXT, created_by UUID, agent_task_id UUID NULL, version INT, created_at, updated_at, archived_at NULL`。

约束：源和目标必须属于同一项目；除明确允许的 `related_to` 外不可自环；活跃边唯一 `(source_node_id,target_node_id,relation)`。删除节点前检查入/出边和文档引用。

#### `evidence_sources`

`id UUID PK, node_id UUID FK, source_kind VARCHAR(24), paper_id UUID NULL, chunk_id UUID NULL, experiment_run_id UUID NULL, asset_id UUID NULL, page_start INT NULL, page_end INT NULL, quote_excerpt TEXT NULL, extraction_method VARCHAR(32), extractor_version VARCHAR(80) NULL, stance evidence_stance, relevance NUMERIC(5,2), verified_by UUID NULL, verified_at TIMESTAMPTZ NULL, created_at`。

约束：`paper/chunk/experiment_run/asset` 至少一个来源存在；摘录仅保存必要短段，完整正文从授权文件读取。

#### `evidence_node_layouts`

`node_id UUID FK, user_id UUID NULL, view_key VARCHAR(40), x NUMERIC(10,2), y NUMERIC(10,2), width NUMERIC(10,2), height NUMERIC(10,2), updated_at, PRIMARY KEY(node_id,user_id,view_key)`。`user_id NULL` 表示项目共享布局。

#### `evidence_comments`

`id UUID PK, node_id UUID FK, author_user_id UUID FK, body TEXT, parent_id UUID NULL, created_at, updated_at, deleted_at NULL`。

### 11.6 文件、数据集与实验

#### `assets`

`id UUID PK, team_id UUID FK, project_id UUID NULL, kind asset_kind, bucket VARCHAR(80), object_key TEXT, original_name TEXT, mime_type VARCHAR(160), size_bytes BIGINT, sha256 CHAR(64), status VARCHAR(24), scan_status VARCHAR(24), metadata JSONB, created_by UUID, created_at, archived_at NULL`。

约束：`UNIQUE(bucket,object_key)`；索引：`(project_id,kind,created_at DESC)`、`sha256`。对象不可公开；下载通过短期签名 URL。

#### `datasets`

`id UUID PK, project_id UUID FK, name VARCHAR(200), description TEXT, license TEXT NULL, sensitivity VARCHAR(24), created_by UUID, created_at, updated_at, archived_at NULL, UNIQUE(project_id,name)`。

#### `dataset_versions`

`id UUID PK, dataset_id UUID FK, version_no INT, manifest_sha256 CHAR(64), schema_json JSONB, statistics JSONB, row_count BIGINT NULL, size_bytes BIGINT, status VARCHAR(24), created_by UUID, created_at, UNIQUE(dataset_id,version_no), UNIQUE(dataset_id,manifest_sha256)`。

#### `dataset_version_files`

`dataset_version_id UUID FK, asset_id UUID FK, relative_path TEXT, ordinal INT, PRIMARY KEY(dataset_version_id,asset_id), UNIQUE(dataset_version_id,relative_path)`。

#### `experiments`

`id UUID PK, project_id UUID FK, cycle_id UUID FK, code VARCHAR(32), name VARCHAR(200), objective TEXT, entrypoint TEXT, code_asset_id UUID FK, container_image TEXT, container_digest TEXT NULL, default_parameters JSONB, resource_spec JSONB, status VARCHAR(24), created_by UUID, version INT, created_at, updated_at, archived_at NULL`。

约束：`UNIQUE(cycle_id,code)`。

#### `experiment_runs`

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `id` | UUID PK | 运行 ID |
| `experiment_id` | UUID FK | 定义 |
| `run_no` | INT | 实验内序号 |
| `status` | experiment_run_status | 状态 |
| `parameters` | JSONB | 固化参数 |
| `code_sha256`,`image_digest` | TEXT | 复现信息 |
| `random_seed` | BIGINT NULL | 随机种子 |
| `resource_request`,`resource_actual` | JSONB | 资源 |
| `runner_job_id` | VARCHAR(160) NULL | 外部执行器 ID |
| `queued_at`,`started_at`,`finished_at` | TIMESTAMPTZ NULL | 时间 |
| `exit_code` | INT NULL | 退出码 |
| `error` | JSONB NULL | 结构化错误 |
| `requested_by` | UUID | 发起人 |
| `created_at` | TIMESTAMPTZ | 创建时间 |

约束：`UNIQUE(experiment_id,run_no)`；状态只能按运行状态机推进。

#### `experiment_run_datasets`

`run_id UUID FK, dataset_version_id UUID FK, mount_path TEXT, access_mode VARCHAR(12) DEFAULT 'read_only', PRIMARY KEY(run_id,dataset_version_id), UNIQUE(run_id,mount_path)`。用关系表固定数据版本，禁止只在 JSON/UUID 数组中保存不可校验引用。

#### `experiment_metrics`

`id BIGSERIAL PK, run_id UUID FK, name VARCHAR(120), step BIGINT, value DOUBLE PRECISION, recorded_at TIMESTAMPTZ, metadata JSONB, UNIQUE(run_id,name,step)`。高频指标可按时间分区。

#### `experiment_artifacts`

`run_id UUID FK, asset_id UUID FK, role VARCHAR(32), name VARCHAR(160), metadata JSONB, created_at, PRIMARY KEY(run_id,asset_id)`。

### 11.7 Agent、Job 与工具调用

#### `agent_definitions`

`id UUID PK, team_id UUID FK, key VARCHAR(80), display_name VARCHAR(160), description TEXT, status VARCHAR(20), active_version_id UUID NULL, created_by UUID, created_at, updated_at, UNIQUE(team_id,key)`。

#### `agent_versions`

`id UUID PK, agent_id UUID FK, version_no INT, role_prompt TEXT, model_provider VARCHAR(80), model_name VARCHAR(120), model_parameters JSONB, tool_policy JSONB, input_schema JSONB, output_schema JSONB, budget_policy JSONB, created_by UUID, created_at, UNIQUE(agent_id,version_no)`。发布后不可修改。

#### `agent_tasks`

`id UUID PK, project_id UUID FK, cycle_id UUID NULL, agent_version_id UUID FK, task_type VARCHAR(80), status job_status, input JSONB, output JSONB NULL, error JSONB NULL, token_usage JSONB, cost_amount NUMERIC(12,6) NULL, budget JSONB, parent_task_id UUID NULL, requested_by UUID, started_at, finished_at, created_at, cancel_requested_at NULL, attempt INT DEFAULT 1`。

索引：`(project_id,status,created_at DESC)`、`(parent_task_id)`。

#### `agent_task_steps`

`id UUID PK, task_id UUID FK, ordinal INT, name VARCHAR(160), status job_status, input_summary JSONB, output_summary JSONB, error JSONB NULL, started_at, finished_at, UNIQUE(task_id,ordinal)`。

#### `agent_tool_calls`

`id UUID PK, task_id UUID FK, step_id UUID NULL, tool_name VARCHAR(160), risk_level VARCHAR(20), arguments_redacted JSONB, result_summary JSONB NULL, status job_status, approval_id UUID NULL, idempotency_key VARCHAR(160), started_at, finished_at, error JSONB NULL`。不得保存密钥、完整 Token 或签名 URL。

#### `agent_memories`

`id UUID PK, project_id UUID FK, agent_id UUID FK, scope VARCHAR(24), content TEXT, summary TEXT, source_refs JSONB, importance NUMERIC(5,2), expires_at TIMESTAMPTZ NULL, superseded_by UUID NULL, embedding_ref VARCHAR(160) NULL, created_at`。长期记忆必须可追溯、可删除、可被新事实取代。

#### `jobs`

统一 Job 投影：`id UUID PK, project_id UUID NULL, kind VARCHAR(80), subject_type VARCHAR(80), subject_id UUID NULL, status job_status, progress NUMERIC(5,2), message TEXT NULL, result_ref JSONB NULL, error JSONB NULL, requested_by UUID, idempotency_key VARCHAR(160) NULL, created_at, started_at, finished_at, heartbeat_at`。领域表仍保存完整业务状态。

### 11.8 写作、审批和审计

#### `documents`

`id UUID PK, project_id UUID FK, cycle_id UUID FK, title TEXT, document_type VARCHAR(32), status VARCHAR(24), current_version_id UUID NULL, created_by UUID, created_at, updated_at, archived_at NULL`。

#### `document_versions`

`id UUID PK, document_id UUID FK, version_no INT, content_markdown TEXT, structure JSONB, content_sha256 CHAR(64), change_summary TEXT, source_agent_task_id UUID NULL, created_by UUID, created_at, UNIQUE(document_id,version_no)`。版本不可更新。

#### `document_claims`

`id UUID PK, document_version_id UUID FK, evidence_node_id UUID FK, anchor JSONB, support_status VARCHAR(24), created_at`。`anchor` 包含 section/path/range，导出前验证仍能定位。

#### `document_suggestions`

`id UUID PK, document_id UUID FK, base_version_id UUID FK, target_section_key VARCHAR(120), patch JSONB, rendered_preview TEXT, status VARCHAR(20), agent_task_id UUID FK, created_at, decided_by UUID NULL, decided_at TIMESTAMPTZ NULL`。`status` 为 pending/accepted/rejected/superseded；接受时在同一事务创建新 Document Version，不能直接覆盖基准版本。

#### `citations`

`id UUID PK, document_version_id UUID FK, paper_id UUID FK, citation_key VARCHAR(80), style_data JSONB, anchors JSONB, created_at, UNIQUE(document_version_id,citation_key)`。

#### `approvals`

`id UUID PK, project_id UUID FK, approval_type VARCHAR(80), subject_type VARCHAR(80), subject_id UUID, status approval_status, risk_level VARCHAR(20), request_reason TEXT, snapshot JSONB, requested_by UUID, assigned_to UUID NULL, expires_at TIMESTAMPTZ NULL, decided_at TIMESTAMPTZ NULL, created_at`。

#### `approval_decisions`

`id UUID PK, approval_id UUID FK, decision VARCHAR(16), comment TEXT NULL, decided_by UUID, created_at`。一个审批最多一个最终决定；更正必须创建新审批。

#### `notifications`

`id UUID PK, user_id UUID FK, type VARCHAR(80), title TEXT, body TEXT, action_url TEXT NULL, read_at TIMESTAMPTZ NULL, created_at`。索引：`(user_id,read_at,created_at DESC)`。

#### `connector_configs`

`id UUID PK, team_id UUID FK, connector_type VARCHAR(80), name VARCHAR(120), status VARCHAR(20), public_config JSONB, secret_ref TEXT NULL, last_checked_at TIMESTAMPTZ NULL, last_error JSONB NULL, created_by UUID, created_at, updated_at, UNIQUE(team_id,connector_type,name)`。密钥保存在外部 Secret Store；本表仅保存引用。

#### `api_keys`

`id UUID PK, team_id UUID FK, created_by UUID FK, name VARCHAR(120), token_prefix VARCHAR(16), token_hash TEXT UNIQUE, scopes TEXT[], expires_at TIMESTAMPTZ NULL, last_used_at TIMESTAMPTZ NULL, revoked_at TIMESTAMPTZ NULL, created_at`。明文 Token 只在创建时显示一次。

#### `audit_logs`

`id UUID PK, team_id UUID FK, project_id UUID NULL, actor_type VARCHAR(20), actor_id UUID NULL, action VARCHAR(120), target_type VARCHAR(80), target_id UUID NULL, before_redacted JSONB NULL, after_redacted JSONB NULL, request_id UUID, ip_hash TEXT NULL, created_at TIMESTAMPTZ`。只追加；按月分区；普通用户不可删除。

#### `outbox_events`

`id UUID PK, aggregate_type VARCHAR(80), aggregate_id UUID, aggregate_version INT, event_type VARCHAR(120), payload JSONB, created_at TIMESTAMPTZ, published_at TIMESTAMPTZ NULL, attempt_count INT DEFAULT 0, last_error TEXT NULL`。索引：未发布事件的部分索引 `(created_at) WHERE published_at IS NULL`。

### 11.9 Neo4j 投影

Neo4j 节点包含 `source_id`、`project_id`、`cycle_id`、`type`、`code`、`title`、`status`、`confidence`、`source_version`。关系包含 `source_edge_id`、`type`、`stance`、`confidence`、`source_version`。投影消费者按 `source_id + version` 幂等 upsert。所有写操作先写 PostgreSQL；禁止直接从前端写 Neo4j。

### 11.10 Milvus Collection

至少建立：

```text
paper_chunks:
  id: VARCHAR primary key (chunk UUID)
  project_id: VARCHAR
  paper_id: VARCHAR
  embedding_model: VARCHAR
  embedding_version: VARCHAR
  vector: FLOAT_VECTOR[provider_dimension]
  created_at: INT64

agent_memories:
  id: VARCHAR primary key
  project_id: VARCHAR
  agent_id: VARCHAR
  vector: FLOAT_VECTOR[provider_dimension]
  created_at: INT64
```

不同维度或不可比较的模型使用不同 Collection/Partition。检索结果返回 UUID 后，权限和正文必须回 PostgreSQL 校验；不能仅凭 Milvus 结果泄露跨项目数据。

---

## 12. 科研生命周期引擎

### 12.1 固定阶段与依赖

```text
topic -> literature -> hypothesis -> experiment -> validation -> writing -> reflection -> evolution
```

生命周期不是简单百分比条，而是服务端状态机。每个周期创建时生成 8 条 `lifecycle_stages`，初始仅 `topic=ready`，其余为 `pending`。上游完成且门禁满足后，下游转为 `ready`。

### 12.2 状态转换

```text
pending -> ready
ready -> running | cancelled
running -> waiting_approval | blocked | completed | failed | cancelled
waiting_approval -> completed | running | blocked
blocked -> running | cancelled
failed -> running (retry) | cancelled
completed -> running (explicit reopen only)
```

规则：

- `pending -> ready` 通常由依赖事件自动触发。
- `running -> completed` 必须先运行阶段门禁校验。
- `completed -> running` 是“重开”，必填原因、增加版本、使所有依赖此结果的下游阶段进入 `blocked` 或 `needs_review`。
- 任何自动转换都写 `stage_transition_events` 和审计日志。
- 客户端提交 `expected_version`；版本不一致返回 409。

### 12.3 各阶段入口、产物与退出门禁

| 阶段 | 入口 | 强制产物 | 默认退出门禁 |
|---|---|---|---|
| 选题 | 周期已创建 | 研究问题、范围、候选比较、风险与创新性报告 | 已采纳一个候选；Owner/Researcher 确认；研究问题非空 |
| 文献 | 选题完成 | 检索式、纳排标准、论文集、覆盖报告 | 至少一条已验证证据；无运行中的必需解析任务；覆盖阈值达到项目配置 |
| 假设 | 文献完成 | 可证伪假设、预测、变量、判定规则 | 至少一个 active Hypothesis；每个假设有关联来源和验证方案 |
| 实验 | 假设完成 | 实验定义、运行、日志、指标、产物 | 至少一个成功运行；代码/镜像/数据/参数 Hash 完整；失败运行已解释 |
| 验证 | 实验完成 | 结果节点、支持/反驳关系、矛盾处理、验证报告 | 关键 Claim 均有支持状态；未解决高优先级矛盾为 0 或经审批接受 |
| 写作 | 验证完成 | 文档、引用、图表、导出 | 引用完整性通过；关键主张有证据；Reviewer 审批 |
| 复盘 | 写作完成 | 复盘报告、失败分析、经验、建议 | 复盘已确认；下一周期建议已接受或明确拒绝 |
| 进化 | 复盘完成 | 下一周期计划或项目结束决定 | 创建下一周期或关闭项目；Owner 确认 |

覆盖阈值等数字允许按项目配置，但必须保存门禁快照，确保历史可解释。默认配置：文献覆盖率 `>= 70%`，关键主张最低证据数 `>= 1`，未解决高优先级矛盾 `= 0`。

### 12.4 阶段进度计算

进度由服务端按完成检查项加权计算，不接受客户端任意写百分比。例如实验阶段：设计已批准 15%、环境已固化 15%、必需运行完成 40%、结果已解析 20%、复现检查 10%。如果项目自定义检查项，权重总和必须等于 100。

### 12.5 Lifecycle API

```text
GET  /api/v1/projects/{project_id}/cycles/{cycle_id}/lifecycle
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:start
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:complete
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:block
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:resume
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}:reopen
GET  /api/v1/projects/{project_id}/cycles/{cycle_id}/stages/{stage_key}/gate
GET  /api/v1/projects/{project_id}/cycles/{cycle_id}/actions
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/actions
PATCH /api/v1/projects/{project_id}/actions/{action_id}
POST /api/v1/projects/{project_id}/actions/{action_id}:complete
```

完成请求示例：

```json
{
  "expected_version": 7,
  "completion_note": "三组必需实验均完成并已关联结果节点",
  "evidence_node_ids": ["node_uuid_1", "node_uuid_2"]
}
```

门禁失败返回 422：

```json
{
  "error": {
    "code": "STAGE_GATE_FAILED",
    "message": "实验阶段尚未满足完成条件",
    "details": {
      "missing": [
        {"code": "REPRODUCIBILITY_HASH_MISSING", "subject_id": "run_uuid"},
        {"code": "REQUIRED_RUN_NOT_SUCCEEDED", "subject_id": "run_uuid_2"}
      ]
    },
    "trace_id": "trace_uuid"
  }
}
```

### 12.6 领域事件

至少发布：`CycleCreated`、`StageReady`、`StageStarted`、`StageBlocked`、`StageCompleted`、`StageReopened`、`CycleCompleted`。事件消费者更新通知、Dashboard 缓存、Agent 任务建议和 Neo4j 投影，但不得让通知失败阻止核心事务。

---

## 13. 文献检索、解析与 RAG

### 13.1 检索流程

```text
User/Agent submits structured query
  -> normalize query and provider filters
  -> create literature_search_run
  -> fan out to configured providers
  -> per-provider rate limit/retry
  -> normalize metadata
  -> DOI/external-id/fuzzy deduplication
  -> rank by relevance, recency and evidence quality
  -> return merged page with source badges
  -> selected results become project_papers
```

必须保留每个结果的 Provider、外部 ID、查询时间和原始元数据。排序公式和模型版本写入 Run，避免无法复现。

### 13.2 PDF 入库流水线

```text
uploaded
 -> malware_scanning
 -> hash_verified
 -> metadata_extraction
 -> text_extraction
 -> needs_ocr (only when text density is insufficient)
 -> section_detection
 -> chunking
 -> embedding
 -> evidence_extraction
 -> ready
```

任一步失败都保留已完成产物和结构化错误；用户可从失败步骤重试。OCR 不应对本来可提取文本的 PDF 默认执行。

### 13.3 Chunk 规则

- 优先按标题、段落和页面边界切分。
- 默认目标 700 tokens，重叠 100 tokens；不得跨越不相关章节盲目拼接。
- 每个 Chunk 保存页码、Section Path、字符范围、内容 Hash、Parser 版本。
- 表格和图注以独立 Chunk 保存并标记类型。
- 重新解析产生新 Parser 版本；旧证据来源保持可追溯，不被静默重定向。

### 13.4 检索增强生成

RAG 请求必须先执行项目权限过滤，再进行混合检索：

```text
BM25/全文检索候选
+ Milvus 向量候选
+ 引用/证据图邻居
-> reciprocal rank fusion
-> optional reranker
-> top-k context with source metadata
-> LLM structured answer
```

返回答案必须包含逐条来源 `paper_id/chunk_id/page` 和置信说明。找不到足够证据时返回“证据不足”，不得让模型补造文献。

### 13.5 证据抽取

Evidence Extraction Agent 输出严格 JSON Schema：主张文本、立场、证据摘录、页码、Chunk、方法、结果数值、置信度和不确定性。服务端验证来源存在、页码合法、摘录可在规范化 Chunk 中定位。未通过验证的节点状态为 `draft`，不能直接支撑已发布 Claim。

### 13.6 文献 API

```text
POST /api/v1/projects/{project_id}/literature-search-runs
GET  /api/v1/projects/{project_id}/literature-search-runs/{run_id}
POST /api/v1/projects/{project_id}/topic-discovery-runs
GET  /api/v1/projects/{project_id}/topic-discovery-runs/{run_id}
GET  /api/v1/projects/{project_id}/topic-candidates
GET  /api/v1/projects/{project_id}/topic-candidates/{candidate_id}
POST /api/v1/projects/{project_id}/topic-candidates/{candidate_id}:accept
POST /api/v1/projects/{project_id}/topic-candidates/{candidate_id}:reject
GET  /api/v1/projects/{project_id}/papers
POST /api/v1/projects/{project_id}/papers
GET  /api/v1/projects/{project_id}/papers/{project_paper_id}
PATCH /api/v1/projects/{project_id}/papers/{project_paper_id}
POST /api/v1/projects/{project_id}/papers/{project_paper_id}:parse
POST /api/v1/projects/{project_id}/papers/{project_paper_id}:extract-evidence
GET  /api/v1/projects/{project_id}/papers/{project_paper_id}/chunks
GET  /api/v1/projects/{project_id}/papers/{project_paper_id}/similar
```

---

## 14. Evidence Graph 业务规则

### 14.1 节点最低字段

| 类型 | 必填业务字段 |
|---|---|
| ResearchQuestion | 问题、范围、目标群体/对象、周期 |
| Paper | `paper_id` |
| Evidence | 来源、立场、摘录/结果、抽取方法 |
| Hypothesis | 可证伪陈述、预测、变量、拒绝准则 |
| Experiment | `experiment_id`、验证目标 |
| Result | `experiment_run_id`、指标/观察、方向 |
| Validation | 判定规则、结论、不确定性 |
| Claim | 可发布陈述、重要级别、支持状态 |
| Dataset | `dataset_version_id` |
| Method | 方法说明和版本/来源 |

### 14.2 边方向规则

```text
Paper/Evidence/Result    -> supports | contradicts -> Hypothesis/Claim
Hypothesis               -> tested_by              -> Experiment
Experiment               -> produces               -> Result
Result                   -> validated_by           -> Validation
Claim                    -> derived_from            -> Evidence/Result/Validation
Paper                    -> cites                   -> Paper
Experiment/Method        -> uses                    -> Dataset
```

服务端根据类型矩阵拒绝无意义关系。例如 Dataset 不能 `contradicts` User，Experiment 不能 `cites` Claim。`related_to` 仅用于无法表达的弱关系，并要求 rationale。

### 14.3 置信度和证据强度

- `confidence` 表示对抽取/关系判断的可信程度，不代表研究结论为真的概率。
- Evidence Strength 由来源质量、直接性、复现性、独立来源数和矛盾惩罚计算。
- 算法版本、输入节点版本和权重写入计算快照。
- UI 必须区分 Agent 估计与人工验证状态。

### 14.4 矛盾工作流

创建 `contradicts` 边后：

1. 更新目标 Hypothesis/Claim 的 `has_unresolved_contradiction` 投影。
2. 生成冲突审阅项，列出双方来源、方法和样本差异。
3. Reviewer 可选择“接受反驳”“证据不足”“适用范围不同”“需新实验”。
4. 决议作为新的 Validation Node，不得删除原反驳边。
5. 高优先级未解决矛盾阻止 Validation/Writing 阶段完成。

### 14.5 Provenance

每个由 Agent 产生的节点、边或来源都必须保存：`agent_task_id`、Agent Version、模型、工具、来源 ID、生成时间、输入摘要和人工验证信息。前端可沿链路追溯到 PDF 页码或 Experiment Run 产物。

---

## 15. 实验系统与计算执行

### 15.1 实验定义

实验定义是可版本化配置，不等于一次运行。创建/修改实验时校验：

- 入口命令只引用容器内工作目录。
- 容器镜像必须是允许 Registry，并在运行时解析为不可变 digest。
- 代码由 Git commit 或代码 Asset Hash 固定。
- 数据集必须引用不可变 Dataset Version。
- 参数符合 JSON Schema；敏感值引用 Secret 名称，不写入数据库明文。
- 资源请求在项目/用户配额内。

### 15.2 运行状态机

```text
queued -> preparing -> running -> uploading_artifacts -> succeeded
   |          |           |                |
   +--------> failed <-----+----------------+
queued/preparing/running -> cancelled
```

Celery 负责任务编排，真正的实验运行器负责隔离容器。Worker 不得直接 `exec` 未隔离的用户代码。

### 15.3 调度与隔离

- CPU、内存、GPU、磁盘和最长运行时间均设硬限制。
- 禁用 privileged、宿主 PID/IPC、Docker Socket、任意设备映射。
- 默认禁用外网；需要外网的实验必须申请明确域名白名单和审批。
- 只读挂载代码和数据；单独可写输出目录。
- 运行使用短期凭据，只允许写入本次 Run 的对象前缀。
- 超时先发送优雅终止，再强制停止；保留最后日志和已上传检查点。

### 15.4 日志、指标与产物

- 标准输出/错误按序号分块写流式通道，并定期归档为 MinIO Asset。
- 指标通过 SDK 或 JSON Lines 上报；无效值不使运行崩溃，但记录解析警告。
- 每个产物完成上传后计算 SHA-256，并写 `experiment_artifacts`。
- `succeeded` 只有在进程退出码为 0 且必需产物成功入库后成立。
- 日志 WebSocket 只发送新增片段；客户端带 `after_seq` 补读。

### 15.5 复现清单

运行详情必须一键导出：项目/实验/Run ID、代码 Hash、镜像 digest、依赖、数据集 manifest Hash、参数、随机种子、资源、开始/结束时间、平台版本和所有产物 Hash。复现检查缺项时 Dashboard 和阶段门禁显示明确警告。

### 15.6 实验 API

```text
GET    /api/v1/projects/{project_id}/experiments
POST   /api/v1/projects/{project_id}/experiments
GET    /api/v1/projects/{project_id}/experiments/{experiment_id}
PATCH  /api/v1/projects/{project_id}/experiments/{experiment_id}
POST   /api/v1/projects/{project_id}/experiments/{experiment_id}/runs
GET    /api/v1/projects/{project_id}/experiment-runs/{run_id}
POST   /api/v1/projects/{project_id}/experiment-runs/{run_id}:cancel
POST   /api/v1/projects/{project_id}/experiment-runs/{run_id}:retry
GET    /api/v1/projects/{project_id}/experiment-runs/{run_id}/logs
GET    /api/v1/projects/{project_id}/experiment-runs/{run_id}/metrics
GET    /api/v1/projects/{project_id}/experiment-runs/{run_id}/artifacts
POST   /api/v1/projects/{project_id}/experiment-runs:compare
```

运行创建返回：

```json
{
  "data": {
    "run_id": "run_uuid",
    "job_id": "job_uuid",
    "status": "queued",
    "position": 2
  },
  "meta": {"request_id": "request_uuid"}
}
```

---

## 16. AI Agent 系统

### 16.1 Agent 角色

| Agent | 核心职责 | 允许的主要工具 | 关键限制 |
|---|---|---|---|
| Research Planner | 分解研究目标、生成计划与阶段建议 | 项目读取、任务创建建议 | 不自动完成阶段 |
| Discovery Agent | 检索趋势、生成选题候选 | 外部文献搜索、相似工作检索 | 选题必须人工采纳 |
| Literature Agent | 查询、筛选、摘要、证据抽取 | 文献源、PDF Parser、RAG | 不得伪造引用 |
| Evidence Agent | 建议节点、关系、矛盾 | Evidence Read/Propose | 高置信关系仍需可追溯 |
| Experiment Agent | 设计实验、分析运行 | 实验读取、创建草稿、运行建议 | 高资源运行需审批 |
| Coding Agent | 生成/修改实验代码草稿 | 沙箱代码、测试 | 不能直接写宿主机或生产分支 |
| Reviewer Agent | 审查证据、方法、引用和结论 | 全项目只读、评论/审批建议 | 不能代替人类最终审批 |
| Writing Agent | 基于证据生成文档 Diff | Evidence Read、Document Suggest | 不直接覆盖正式文档 |
| Reflection Agent | 复盘失败、资源和下一周期 | 项目全链路只读、建议创建 | 不自动改变研究方向 |

### 16.2 Orchestrator

Orchestrator 接受目标后生成 DAG，而不是让单个 Agent 无限循环。每一步包含：Agent Version、输入 Schema、依赖、工具权限、预算、超时、成功条件和是否需审批。DAG 保存为可审计结构；运行中修改计划必须创建新 Plan Revision。

### 16.3 标准任务输入输出

```json
{
  "task_id": "task_uuid",
  "task_type": "literature.evidence_extract",
  "project": {"id": "project_uuid", "cycle_id": "cycle_uuid"},
  "objective": "提取与 H1 直接相关的支持和反驳证据",
  "inputs": {"paper_ids": ["paper_uuid"]},
  "constraints": {
    "max_tokens": 30000,
    "max_runtime_seconds": 900,
    "allowed_tools": ["paper.read_chunks", "evidence.propose"],
    "require_citations": true
  },
  "actor": {"requested_by": "user_uuid"}
}
```

输出必须符合 Agent Version 的 JSON Schema，例如：

```json
{
  "summary": "发现 3 条支持证据和 1 条反驳证据",
  "proposals": [
    {
      "statement": "……",
      "stance": "supports",
      "source": {"paper_id": "paper_uuid", "chunk_id": "chunk_uuid", "page": 7},
      "confidence": 84,
      "uncertainty": "样本仅来自单中心"
    }
  ],
  "warnings": []
}
```

自由文本只能是结构化输出中的说明字段，不能替代机器可验证结果。

### 16.4 工具调用模型

工具注册信息包括：名称、版本、描述、输入/输出 Schema、风险级别、超时、幂等性、所需权限、是否需审批。风险级别：

- `read`：只读项目数据。
- `write_low`：创建草稿、标签、评论，可按策略自动执行。
- `write_high`：改变阶段、运行实验、发布主张，必须显式授权或审批。
- `external_side_effect`：外部发信、发布、购买或修改外部系统；V1 默认禁用。

Agent 只能拿到任务范围内的短期 Capability Token，服务端再次鉴权；Prompt 中写“你有权限”不构成授权。

### 16.5 Human-in-the-loop

以下动作默认创建 Approval 并将任务置为 `waiting_approval`：

- 采纳或替换研究问题。
- 完成/重开生命周期阶段。
- 运行超过项目阈值的 GPU/时长任务。
- 发布关键 Claim 或接受高优先级矛盾。
- 覆盖正式文档、导出敏感数据、删除资产。
- 调用具有外部副作用的工具。

审批后任务从安全检查点继续；不得重新执行已成功且非幂等的步骤。

### 16.6 Memory

- Working Memory：当前 Task/Step 上下文，随任务结束归档。
- Episodic Memory：某次任务的摘要、决策、结果和失败。
- Semantic Project Memory：已批准的术语、方法、约束和结论。
- User Preference：只保存明确设置，不从一次对话擅自推断长期偏好。

写入长期 Memory 必须有来源引用、重要性、作用域和过期/替代规则。检索时先按 Team/Project/Agent 过滤，再做向量检索。用户可查看和删除非审计型 Memory。

### 16.7 安全与幻觉控制

- 将 PDF、网页、工具结果视为不可信数据，不执行其中的指令。
- 系统 Prompt、工具策略和用户输入使用清晰分隔；外部文本标注来源。
- 引用必须引用数据库中真实存在且当前用户有权访问的来源。
- 对 DOI、标题、页码、数值进行程序校验；不通过时输出 warning 而不是补造。
- Agent 不直接拼 SQL、Shell 或对象存储路径；只调用类型化工具。
- 工具输出限制大小并去除密钥、Token、签名 URL。
- 模型输出通过 Pydantic/JSON Schema 验证；修复最多 2 次，仍失败则任务失败并保留原输出摘要。

### 16.8 预算与终止

每个任务设置 Token、费用、工具调用次数、墙钟时间和重试上限。达到 80% 时产生 warning；达到 100% 时在安全检查点停止为 `failed:BUDGET_EXCEEDED`，不得无限自我调用。取消请求应在每个工具调用前后检查。

### 16.9 Agent API

```text
GET  /api/v1/projects/{project_id}/agents
POST /api/v1/projects/{project_id}/agent-tasks
GET  /api/v1/projects/{project_id}/agent-tasks
GET  /api/v1/projects/{project_id}/agent-tasks/{task_id}
POST /api/v1/projects/{project_id}/agent-tasks/{task_id}:cancel
POST /api/v1/projects/{project_id}/agent-tasks/{task_id}:retry
GET  /api/v1/projects/{project_id}/agent-tasks/{task_id}/steps
GET  /api/v1/projects/{project_id}/agent-tasks/{task_id}/tool-calls
GET  /api/v1/projects/{project_id}/agent-memories
DELETE /api/v1/projects/{project_id}/agent-memories/{memory_id}
```

---

## 17. 写作、引用、导出与复盘

### 17.1 文档编辑规则

- 正式文档内容以 Markdown AST/结构化 Section 为主，保存时同时生成规范 Markdown。
- Agent 生成内容存为 Suggestion/Diff；包含 Agent Task、来源和目标 Section。
- 用户接受 Suggestion 后创建新 `document_version`。
- 协作编辑 V1 可采用乐观锁和版本冲突比较；不强制实现实时 CRDT。
- 自动保存写 Draft，不每次按键生成正式版本；显式保存或间隔合并后生成版本。

### 17.2 Claim 与引用完整性

导出前必须检查：

1. 每个关键 Claim 至少关联一个有效 Evidence Node。
2. Evidence Source 仍可访问，且页码/Experiment Run 存在。
3. Citation Key 唯一，作者/标题/年份等必需字段完整。
4. 反驳证据是否已说明或经审批接受。
5. 图表 Asset Hash 和图注存在。
6. 没有未解决的 Agent 占位文本或“待补引用”。

检查结果分 error/warning；error 阻止“正式导出”，但用户可生成带明显水印的 Draft Export。

### 17.3 导出流水线

```text
snapshot document version
 -> resolve citations and assets
 -> run integrity checks
 -> render Markdown/LaTeX/DOCX
 -> compile PDF when requested
 -> store export Asset + manifest
 -> return signed download URL
```

Manifest 包含文档版本 Hash、引用列表、图表 Hash、模板版本、编译器版本和生成时间。

### 17.4 Writing API

```text
GET   /api/v1/projects/{project_id}/documents
POST  /api/v1/projects/{project_id}/documents
GET   /api/v1/projects/{project_id}/documents/{document_id}
PATCH /api/v1/projects/{project_id}/documents/{document_id}/draft
POST  /api/v1/projects/{project_id}/documents/{document_id}/versions
GET   /api/v1/projects/{project_id}/documents/{document_id}/versions
POST  /api/v1/projects/{project_id}/documents/{document_id}:integrity-check
POST  /api/v1/projects/{project_id}/documents/{document_id}:export
POST  /api/v1/projects/{project_id}/documents/{document_id}/suggestions
POST  /api/v1/projects/{project_id}/documents/{document_id}/suggestions/{suggestion_id}:accept
POST  /api/v1/projects/{project_id}/documents/{document_id}/suggestions/{suggestion_id}:reject
```

### 17.5 Reflection

复盘运行输入为固定周期快照，输出必须包含可计算指标和来源：目标完成率、阶段耗时、失败/取消运行、资源消耗、证据覆盖变化、矛盾数量、Agent 成功率和人工修改率。建议被采纳时创建下一周期的 Draft，不修改已完成周期。

复盘报告使用 `documents.document_type='reflection'` 和不可变 Document Version 保存；结构化建议位于版本的 `structure` 字段并引用 Evidence/Experiment/Agent Task。接口：

```text
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/reflection-runs
GET  /api/v1/projects/{project_id}/cycles/{cycle_id}/reflection-runs/{run_id}
GET  /api/v1/projects/{project_id}/cycles/{cycle_id}/reflection
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/reflection/recommendations/{recommendation_id}:accept
POST /api/v1/projects/{project_id}/cycles/{cycle_id}/reflection/recommendations/{recommendation_id}:reject
```

接受建议时要么创建 `research_action`，要么创建下一周期 Draft；请求体必须明确目标，不能由服务端猜测。

---

## 18. HTTP API 统一设计

### 18.1 基础约定

- Base URL：`/api/v1`。
- Content-Type：JSON 使用 `application/json`；上传使用签名 URL，不让大文件穿过 API 进程。
- 时间：ISO 8601 UTC，例如 `2026-08-16T06:00:00Z`。
- ID：字符串形式 UUID。
- 分页：Cursor Pagination；默认 20，最大 100。
- 排序字段使用白名单；禁止把任意用户字符串拼入 SQL。
- 删除成功返回 204；创建同步资源返回 201；异步任务返回 202。
- OpenAPI 是接口契约源，CI 检查生成的前端类型无未提交变化。

成功响应：

```json
{
  "data": {},
  "meta": {
    "request_id": "request_uuid"
  }
}
```

列表响应：

```json
{
  "data": [],
  "meta": {
    "request_id": "request_uuid",
    "page": {"next_cursor": "opaque_or_null", "has_more": false}
  }
}
```

错误响应：

```json
{
  "error": {
    "code": "RESOURCE_VERSION_CONFLICT",
    "message": "资源已被其他用户更新",
    "field_errors": [],
    "details": {"current_version": 8},
    "trace_id": "trace_uuid"
  }
}
```

### 18.2 状态码

| 状态码 | 用途 |
|---:|---|
| 200 | 查询/更新成功 |
| 201 | 同步创建成功 |
| 202 | 已创建异步 Job |
| 204 | 删除/无正文操作成功 |
| 400 | 请求格式或不支持参数 |
| 401 | 未登录/Token 无效 |
| 403 | 已登录但无权限 |
| 404 | 资源不存在或按安全策略不可见 |
| 409 | 版本冲突、唯一约束、非法当前状态 |
| 413 | 文件或请求过大 |
| 422 | 字段/业务门禁校验失败 |
| 429 | 限流/配额耗尽 |
| 502/503 | 外部 Provider 或依赖暂不可用 |

### 18.3 鉴权 API

```text
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/me
POST /api/v1/auth/password/forgot
POST /api/v1/auth/password/reset
POST /api/v1/auth/ws-token
```

Access Token 默认 15 分钟，只存内存；Refresh Token 默认 7 天，使用 `Secure + HttpOnly + SameSite=Lax` Cookie 并旋转。退出撤销当前 Session。

### 18.4 Team、项目与周期 API

```text
GET    /api/v1/teams
POST   /api/v1/teams
GET    /api/v1/teams/{team_id}/members
POST   /api/v1/teams/{team_id}/members
PATCH  /api/v1/teams/{team_id}/members/{user_id}
DELETE /api/v1/teams/{team_id}/members/{user_id}

GET    /api/v1/projects
POST   /api/v1/projects
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}
POST   /api/v1/projects/{project_id}:archive
POST   /api/v1/projects/{project_id}:restore
GET    /api/v1/projects/{project_id}/dashboard
GET    /api/v1/projects/{project_id}/members
POST   /api/v1/projects/{project_id}/members
PATCH  /api/v1/projects/{project_id}/members/{user_id}
DELETE /api/v1/projects/{project_id}/members/{user_id}

GET    /api/v1/projects/{project_id}/cycles
POST   /api/v1/projects/{project_id}/cycles
GET    /api/v1/projects/{project_id}/cycles/{cycle_id}
PATCH  /api/v1/projects/{project_id}/cycles/{cycle_id}
POST   /api/v1/projects/{project_id}/cycles/{cycle_id}:activate
POST   /api/v1/projects/{project_id}/cycles/{cycle_id}:complete
```

Topic Candidate、Research Action 和 Lifecycle 命令的完整路径分别定义于第 13.6 节和第 12.5 节；所有命令仍遵守本节的鉴权、幂等和错误响应约定。

### 18.5 Asset 与数据集 API

```text
POST /api/v1/projects/{project_id}/assets/uploads:initiate
POST /api/v1/projects/{project_id}/assets/uploads/{upload_id}:complete
POST /api/v1/projects/{project_id}/assets/uploads/{upload_id}:abort
GET  /api/v1/projects/{project_id}/assets
GET  /api/v1/projects/{project_id}/assets/{asset_id}
GET  /api/v1/projects/{project_id}/assets/{asset_id}/download-url
POST /api/v1/projects/{project_id}/assets/{asset_id}:archive

GET  /api/v1/projects/{project_id}/datasets
POST /api/v1/projects/{project_id}/datasets
GET  /api/v1/projects/{project_id}/datasets/{dataset_id}
POST /api/v1/projects/{project_id}/datasets/{dataset_id}/versions
GET  /api/v1/projects/{project_id}/dataset-versions/{version_id}
GET  /api/v1/projects/{project_id}/dataset-versions/{version_id}/preview
```

### 18.6 Approval、通知与 Job API

```text
GET  /api/v1/projects/{project_id}/approvals
POST /api/v1/projects/{project_id}/approvals
GET  /api/v1/projects/{project_id}/approvals/{approval_id}
POST /api/v1/projects/{project_id}/approvals/{approval_id}:approve
POST /api/v1/projects/{project_id}/approvals/{approval_id}:reject
POST /api/v1/projects/{project_id}/approvals/{approval_id}:cancel

GET  /api/v1/notifications
POST /api/v1/notifications/{notification_id}:read
POST /api/v1/notifications:read-all

GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}:cancel
POST /api/v1/jobs/{job_id}:retry
```

### 18.7 设置与连接器 API

```text
GET    /api/v1/settings/profile
PATCH  /api/v1/settings/profile
GET    /api/v1/teams/{team_id}/connectors
POST   /api/v1/teams/{team_id}/connectors
PATCH  /api/v1/teams/{team_id}/connectors/{connector_id}
POST   /api/v1/teams/{team_id}/connectors/{connector_id}:test
DELETE /api/v1/teams/{team_id}/connectors/{connector_id}
GET    /api/v1/teams/{team_id}/api-keys
POST   /api/v1/teams/{team_id}/api-keys
POST   /api/v1/teams/{team_id}/api-keys/{key_id}:revoke
```

创建 API Key 的明文只返回一次；连接器测试调用最小真实健康检查。未配置密钥时返回 `PROVIDER_NOT_CONFIGURED`，不得使用测试凭据。

### 18.8 Idempotency

实验运行、Agent 任务、导出、Discovery、解析和批量上传完成接口必须支持 `Idempotency-Key`。服务端按 `actor + route + key` 保存请求 Hash 和结果至少 24 小时：同 Key 同 Body 返回原结果；同 Key 不同 Body 返回 409。

### 18.9 WebSocket 事件

统一事件格式：

```json
{
  "seq": 1842,
  "type": "experiment.run.progress",
  "project_id": "project_uuid",
  "subject_id": "run_uuid",
  "occurred_at": "2026-08-16T06:01:05Z",
  "data": {"status": "running", "progress": 42.5}
}
```

至少支持：

```text
job.updated
agent.task.updated
agent.tool.approval_required
experiment.run.updated
experiment.log.appended
literature.parse.updated
evidence.index.updated
lifecycle.stage.updated
approval.created
notification.created
system.health.changed
```

事件载荷仅含 UI 更新所需摘要；正文和日志通过 REST 增量获取。

### 18.10 UI—API—存储追踪矩阵

| UI 操作 | API | PostgreSQL/异步产物 |
|---|---|---|
| 点击“刷新发现” | POST topic-discovery-runs | discovery run、topic candidates、Job |
| 采纳选题 | POST topic-candidates/{id}:accept | candidate、stage event、audit |
| 上传 PDF | upload initiate/complete | asset、paper_file、parse Job |
| 关联证据 | POST node source | evidence_source、outbox、Neo4j 投影 |
| 拖动图节点 | PUT evidence/layout | evidence_node_layouts |
| 标记下一步完成 | POST actions/{id}:complete | action/status、audit、可能的 stage event |
| 创建实验运行 | POST experiment runs | experiment_run、Job、Runner |
| 查看实时日志 | WS + GET logs | log stream + MinIO 归档 |
| 启动 Agent | POST agent-tasks | agent_task、steps、tool calls |
| 批准任务 | POST approval:approve | decision、task resume event、audit |
| 接受写作建议 | POST suggestion:accept | document_version、claims/citations |
| 导出论文 | POST document:export | export Job、Asset、manifest |

---

## 19. 权限、安全与合规

### 19.1 授权模型

授权按以下顺序求值：平台用户状态 -> Team Membership -> Project Membership -> 项目角色 -> 资源级约束 -> Tool/Action 风险策略。权限拒绝默认失败关闭（fail closed）。批量接口逐项检查，不能因用户有一个项目权限而读取其他项目 ID。

### 19.2 数据隔离

- 所有项目查询必须限定允许的 `project_id`；Repository 接口显式接收 Access Context。
- 下载签名 URL 只在权限验证后创建，默认有效 5 分钟。
- Milvus 查询先指定项目 Partition/过滤条件；返回结果再回主库鉴权。
- Neo4j 查询必须包含 `project_id`，并限制最大深度、节点数和执行时间。
- 测试中必须包含跨团队 UUID 猜测访问，预期 403/404 且无数据侧漏。

### 19.3 Web 安全

- HTTPS only；生产启用 HSTS、CSP、X-Content-Type-Options、Referrer-Policy。
- CORS 使用明确域名白名单；禁止生产 `*`。
- Refresh Cookie 场景对状态改变端点执行 Origin/CSRF 防护。
- 登录、密码重置、搜索 Provider、Agent 启动和签名 URL 端点分别限流。
- 用户 Markdown 和论文文本输出时转义；禁止未经净化的 HTML 注入。
- 数据库使用参数化查询；任何动态排序/字段名使用白名单。

### 19.4 文件安全

- 限制文件大小、扩展名与 MIME，并检查 Magic Bytes。
- 上传后先进入 quarantine；恶意扫描完成前不可预览或交给 Parser。
- PDF Parser、OCR、LaTeX 编译在无网络、低权限、有限资源的隔离容器运行。
- 解压归档防止 Zip Slip、压缩炸弹和符号链接逃逸。
- 原始文件名只作显示，MinIO Object Key 使用服务端生成值。

### 19.5 Agent 与实验安全

- 论文/网页/工具输出均视为潜在 Prompt Injection；只作为引用数据区传递。
- Tool 调用由服务端策略决定，不由模型自行声明权限。
- URL 抓取器防止 SSRF：禁止私网、Metadata IP、非 HTTP(S)、重定向到受限地址。
- Coding/Experiment Agent 仅在沙箱内运行代码；API 服务不执行模型生成 Shell。
- Secret 由密钥管理或环境注入，日志和数据库只保存引用名。
- 外部副作用工具 V1 默认关闭；开启需管理员配置和每次审批。

### 19.6 审计与保留

必须审计：登录/失败登录、成员与权限、项目归档、阶段转换、审批、实验运行/取消、Agent 高风险工具、资产下载/导出、连接器和密钥配置。审计日志默认保留 365 天或按组织策略；用户删除请求不能删除依法/策略要求保留的审计记录，但应去标识化不必要字段。

### 19.7 Secret 与配置

- `.env.example` 只放变量名和安全示例，不提交真实密钥。
- 密钥在 UI 中仅显示 Provider、尾四位或“已配置”。
- 日志过滤 `authorization/cookie/api_key/token/password/presigned_url`。
- 生产 Secret 使用 Secret Manager/Kubernetes Secret/Docker Secret；不要烘焙进镜像。

---

## 20. 部署与运行

### 20.1 Docker Compose 服务

```text
reverse-proxy
frontend
api
worker-default
worker-literature
worker-embedding
worker-agent
worker-export
experiment-runner
postgres
redis
minio
neo4j
milvus
etcd
otel-collector
prometheus        (observability profile)
grafana           (observability profile)
loki              (observability profile)
```

Milvus 使用独立 bucket/prefix；业务对象与 Milvus 内部对象不能混放。实验运行器与公共 API 网络隔离。生产不把 PostgreSQL、Redis、MinIO、Neo4j、Milvus 端口暴露到公网。

### 20.2 本地启动

项目必须提供：

```text
docker compose --profile core up -d
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed --profile demo
```

首次启动流程：依赖健康 -> migration -> 可选 seed -> API ready -> Frontend ready。Migration 失败时 API 不应以“ready”状态提供旧 Schema 服务。

### 20.3 环境变量

| 变量 | 必需 | 说明 |
|---|:---:|---|
| `APP_ENV` | 是 | development/test/production |
| `APP_BASE_URL` | 是 | 外部访问 URL |
| `DATABASE_URL` | 是 | PostgreSQL DSN |
| `REDIS_URL` | 是 | Redis DSN |
| `JWT_SIGNING_KEY` | 是 | JWT 签名密钥 |
| `ACCESS_TOKEN_TTL_MINUTES` | 否 | 默认 15 |
| `REFRESH_TOKEN_TTL_DAYS` | 否 | 默认 7 |
| `MINIO_ENDPOINT` | 是 | MinIO 内部地址 |
| `MINIO_ACCESS_KEY/SECRET_KEY` | 是 | 对象存储凭据 |
| `MINIO_BUCKET_ASSETS` | 是 | 业务 Asset bucket |
| `NEO4J_URI/USER/PASSWORD` | 是 | 图数据库 |
| `MILVUS_URI` | 是 | 向量库 |
| `LLM_PROVIDER` | 否 | 未配置时 Agent 显示不可用 |
| `LLM_API_KEY` | 否 | Provider Secret |
| `EMBEDDING_PROVIDER/MODEL` | 否 | 未配置时向量功能降级 |
| `OCR_PROVIDER` | 否 | 可选 OCR |
| `LITERATURE_*_API_KEY` | 否 | 各论文源凭据 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 否 | Telemetry |
| `EXPERIMENT_RUNNER_ENDPOINT` | 是 | 隔离运行器 |
| `ALLOWED_ORIGINS` | 是 | CORS 白名单 |

应用启动时验证配置组合；生产缺少必要密钥必须失败启动，不能使用开发默认密钥。

### 20.4 数据卷与持久化

- PostgreSQL、MinIO、Neo4j、Milvus/etcd 使用命名卷或外部持久化卷。
- Redis 的任务 Broker 使用 AOF；Redis 丢失仍可从业务表识别未完成 Job 并人工/自动恢复。
- Frontend/API/Worker 镜像不可写持久业务文件。

### 20.5 备份与恢复

- PostgreSQL：每日全量 + 持续 WAL（生产），保留策略可配置。
- MinIO：版本化/生命周期策略；重要 bucket 异地复制或定期快照。
- Neo4j/Milvus 为可重建投影，但生产可备份以缩短恢复时间。
- 每个正式导出物包含 Manifest，便于独立校验。
- 每季度执行恢复演练：恢复数据库和对象后重建 Neo4j/Milvus，并验证 Hash。

### 20.6 生产扩展

- API 无状态水平扩展。
- Worker 按 Queue 独立扩展；Embedding/Agent/Experiment 分别限流。
- 实验运行迁移为 Kubernetes Job 或受控计算集群时，保持 `ExperimentRunner` 接口不变。
- 迁移微服务的触发条件是独立伸缩、故障隔离或团队所有权的真实需求，不是预先拆分。

---

## 21. 日志、监控和运维

### 21.1 结构化日志

日志字段至少包括：`timestamp`、`level`、`service`、`environment`、`trace_id`、`request_id`、`user_id`、`team_id`、`project_id`、`job_id`、`event`、`duration_ms`、`error_code`。不得记录论文全文、用户 Prompt 全文、Token、Cookie、Secret 或签名 URL。

### 21.2 指标

必须采集：

- API 请求量、P50/P95/P99、4xx/5xx、数据库连接池。
- Celery Queue 长度、任务等待/执行时间、重试/失败/Dead Letter。
- 各 Literature Provider 成功率、限流和延迟。
- PDF 解析/OCR/Embedding 吞吐和失败率。
- Agent Token、费用、工具失败、审批等待、任务成功率。
- 实验排队时长、CPU/GPU 利用、失败原因、产物上传失败。
- Neo4j/Milvus 投影延迟、Outbox backlog。
- MinIO 容量和 Hash 校验错误。

### 21.3 告警

高优先级告警：API readiness 失败、PostgreSQL 不可用、Outbox backlog 持续增长、任务心跳丢失、对象校验错误、实验逃逸/安全策略违规。外部论文源单源故障为 degraded 告警，不应触发平台整体宕机页。

### 21.4 管理操作

提供受限管理命令：重投 Outbox、重建项目 Neo4j 投影、重建 Milvus 索引、重试失联 Job、验证对象 Hash、清理过期签名上传。每个操作必须 dry-run 或明确目标，并写审计日志。

---

## 22. 测试与质量要求

### 22.1 测试层次

| 层次 | 必测内容 |
|---|---|
| Unit | 状态机、门禁、权限策略、覆盖率计算、去重、关系矩阵、预算 |
| Component | 卡片、表格、表单、Graph Node、Inspector、错误/空状态 |
| API Contract | OpenAPI、Schema、状态码、错误码、分页、ETag、幂等 |
| Integration | PostgreSQL、Redis、MinIO、Neo4j、Milvus、Celery |
| Adapter | 文献/LLM/OCR Provider 的正常、限流、超时、错误映射 |
| E2E | 用户关键闭环与权限拒绝 |
| Visual Regression | 两张基准页面 1440 × 900 截图 |
| Security | 越权、SSRF、上传、XSS、Prompt Injection、沙箱策略 |
| Performance | Dashboard、列表、图查询、并发 Job、日志流 |

核心状态机、授权策略、资产 Hash、审批和 Agent 工具策略分支覆盖率至少 90%；后端总体语句覆盖率至少 80%。覆盖率不能替代场景测试。

### 22.2 必需 E2E 场景

1. 注册/登录 -> 创建 Team -> 创建项目 -> 创建周期 -> Dashboard 可刷新。
2. 启动选题发现 -> 查看真实 Job -> 采纳候选 -> topic 阶段完成。
3. 上传 PDF -> 解析 -> Chunk/Embedding -> 从页码创建证据节点。
4. 创建 Hypothesis -> 关联支持和反驳证据 -> 查看冲突。
5. 创建实验 -> 运行 -> 实时日志 -> 指标/产物 -> 结果节点。
6. 完成验证门禁 -> Agent 生成写作建议 -> 用户接受 -> 导出文档。
7. Reviewer 拒绝阶段审批 -> 填写原因 -> 发起人修复并重新提交。
8. Owner 可操作、Guest 只读；Guest 直接调用写 API 返回 403。
9. 刷新浏览器后项目、图布局、任务状态和文档版本仍存在。
10. 外部 Provider 未配置/限流/超时时，UI 明确显示失败或降级，不产生假结果。

### 22.3 视觉回归

基准环境：Chromium 固定版本、`1440 × 900`、100% 缩放、固定字体、禁用动画、固定 seed 数据。验收：

- Sidebar、Header、两列 Dashboard 和三栏 Workspace 边界误差不超过 `2px`。
- 字号、行高、圆角、边框、主色必须与本文令牌一致。
- 组件级截图像素差异不超过 0.5%（抗锯齿区域可设置小阈值）。
- 页面级截图差异不超过 1%；任何结构性位移即失败，不能用提高阈值掩盖。
- Skeleton、Empty、Error、Popover、Modal 另存基准图。

若原始参考图可加入仓库，以它为最终视觉基线；本文尺寸是没有 Figma 标尺时的确定性反推值。

### 22.4 API 与数据库测试

- 每个写接口验证成功、401、403、422、409 和审计记录。
- 测试事务回滚、Outbox 同事务、消费者幂等和乱序事件。
- Migration 从空库升级成功，并至少测试前一发布版本升级。
- 使用 Testcontainers 或等价真实依赖；不要用 SQLite 替代 PostgreSQL 作为唯一集成测试。

### 22.5 故障测试

- Worker 在任务中途重启，Job 可检测心跳超时并恢复/失败。
- Neo4j/Milvus 暂停时主业务写入成功并显示 indexing/degraded，恢复后追平。
- MinIO 上传完成前断线，可续传或安全中止。
- Refresh Token 重放导致 family 撤销。
- 实验超时、OOM、用户取消、产物上传失败分别产生不同错误码。

### 22.6 性能基线

在 4 vCPU/16GB 的本地集成环境和规定 seed 数据下：

- Dashboard 聚合 API P95 < 500ms（不含首次冷启动）。
- 普通分页列表 P95 < 300ms。
- 500 节点/1,500 边子图 API P95 < 1s；前端首次可交互 < 2s。
- WebSocket Job 状态从服务端提交到 UI 展示 P95 < 1s。
- 100MB 分片上传不占用 API 进程等量内存。

外部 Provider 和 LLM 延迟不纳入同步 API 基线，它们必须异步化。

---

## 23. 验收标准

### 23.1 UI 验收

- [ ] Dashboard 与 Evidence Workspace 在 1440 × 900 下满足坐标、尺寸和视觉令牌。
- [ ] 所有菜单均有真实路由和页面，不出现空白占位。
- [ ] 所有按钮具备 Hover、Focus、Disabled、Loading、Success/Error 状态。
- [ ] 表格、图表、Timeline 和 Graph 数据均来自 API。
- [ ] 刷新页面后选中项目/周期、任务和持久业务状态正确恢复。
- [ ] 无权限、空数据、外部服务未配置时有准确界面。

### 23.2 功能验收

- [ ] 能完成选题至进化的完整研究周期。
- [ ] 文献可搜索/上传/解析/OCR/Embedding/抽取证据。
- [ ] Evidence Graph 可编辑、溯源、表达支持与反驳。
- [ ] 实验可隔离运行、查看日志、保存指标和产物并复现。
- [ ] Agent 可真实执行工具、受预算和权限控制、可审批与重试。
- [ ] 写作建议不覆盖正式内容；引用和主张完整性可验证。
- [ ] 文件、数据、代码、模型和导出物有版本与 SHA-256。
- [ ] Owner/Researcher/Reviewer/Guest 权限符合矩阵。

### 23.3 工程验收

- [ ] 一条命令可启动核心 Docker Compose 环境。
- [ ] Migration、Seed、测试和构建命令有 README。
- [ ] OpenAPI、前端类型、数据库模型和本文接口一致。
- [ ] CI 运行 lint、typecheck、unit、integration、E2E 和 visual tests。
- [ ] 没有提交 Secret、生产签名 URL、真实论文全文或用户敏感数据。
- [ ] 日志、指标、Trace 和审计能定位一次失败操作。
- [ ] 备份、恢复和投影重建有可执行说明。

### 23.4 不可接受的“伪完成”

以下任一存在即验收失败：

- 点击按钮只 Toast “成功”而后端无状态变化。
- 图表、统计、任务状态写死在组件内。
- 实验运行实际只是定时器模拟进度。
- Agent 返回静态字符串或不验证引用。
- 上传文件仅保存在浏览器或 API 临时目录。
- 权限只在前端隐藏按钮。
- Neo4j/Milvus 失败导致静默丢数据，且无重建能力。
- 接口返回 200 但内部任务已经失败。
- 存在 `TODO: implement`、空函数、永远返回成功的 Provider Stub 出现在 production 路径。

---

## 24. 开发阶段与每阶段验证

### Phase 0：工程基线

实现 Monorepo、Compose、Frontend/API、PostgreSQL、Redis、MinIO、Migration、配置、日志、CI。

验证：空库 Migration；核心服务健康；Frontend 可调用 `/health/ready`；Secret 扫描通过。

### Phase 1：身份、团队、项目与 UI Shell

实现登录、Token 旋转、Team/Project RBAC、AppShell、WorkspaceShell、项目/周期 CRUD 和确定性 seed。

验证：权限矩阵测试；跨团队访问失败；两种 Shell 视觉回归通过。

### Phase 2：Dashboard 与生命周期

实现 8 阶段状态机、门禁框架、Dashboard 聚合、审批基础、通知和两张页面的静态结构接真实 API。

验证：阶段非法转换失败；所有 Dashboard 卡片刷新持久；页面截图通过。

### Phase 3：文献、资产与 Evidence Graph

实现签名上传、PDF 解析、OCR 适配、Chunk、Embedding、文献检索适配器、证据节点/边、Neo4j 投影和 Inspector。

验证：上传到页码证据的 E2E；Provider 失败降级；投影重建；跨项目向量检索隔离。

### Phase 4：实验系统

实现 Dataset Version、实验定义、隔离 Runner、队列、日志、指标、产物、运行对比和复现清单。

验证：成功、失败、超时、取消、OOM；产物 Hash；无特权/无宿主逃逸。

### Phase 5：Agent 系统

实现 Provider 抽象、Agent Version、DAG、工具注册、任务/步骤、Memory、预算、审批暂停与恢复。

验证：引用校验、Prompt Injection 样例、工具越权拒绝、预算终止、幂等恢复。

### Phase 6：写作、复盘与导出

实现文档版本、Suggestion Diff、Claim/Citation、完整性检查、Markdown/LaTeX/DOCX/PDF 导出和 Reflection。

验证：无来源 Claim 阻止正式导出；版本恢复；导出 Manifest；下一周期 Draft。

### Phase 7：加固与发布

完成性能、安全、可观测性、备份恢复、Runbook、全量 E2E 和视觉验收。

验证：本文 23 节所有复选项通过；无 P0/P1 缺陷；恢复演练成功。

每个 Phase 都必须可运行、可测试、可演示，不能等到最后一次性连接前后端。

---

## 25. 确定性 Demo Seed

Seed 只用于 development/test，必须通过显式命令运行，生产默认不加载。Seed 固定创建：

- Team：“研启智链研究组”。
- 4 个用户，分别对应 Owner、Researcher、Reviewer、Guest。
- Project：“基于多模态表征学习的蛋白质-小分子相互作用预测”。
- 当前 Cycle：第 3 周期，Experiment 阶段进行中，进度 62%。
- Dashboard 统计：532 篇文献、28 次实验运行、3 个数据集、14 张图表。
- 生命周期状态按 6.2 表格。
- 3 个 Topic Candidate，分别为高优先级、中优先级、探索中。
- 6 个 Evidence 主链节点 RQ1/P1/H1/E1/V1/C1，位置按 7.4。
- 至少一条支持边和一条反驳边、一个未解决矛盾。
- 3 条待审批、一条下一步行动、6 个 Agent 健康状态。
- 趋势数据 `48,55,61,67,69,62`。

Seed 使用稳定键进行幂等 upsert；重复运行不得生成重复项目或改变测试基准 UUID 映射。

---

## 26. 代码生成模型执行约束

### 26.1 执行顺序

代码模型必须先建立 Schema/OpenAPI/状态机和最小纵向闭环，再实现页面。推荐每次只完成一个可验证切片，例如：

```text
Lifecycle table + service + API + Timeline query hook + component + tests
```

不得先生成全部页面静态稿，再把后端长期留空；也不得一次生成所有模块而不运行测试。

### 26.2 每次修改要求

1. 说明本次实现对应本文哪一节。
2. 只修改必要文件，遵循已有目录和风格。
3. 先写/更新测试，再实现行为。
4. 运行最窄相关测试，再运行受影响的集成测试。
5. 如果外部凭据缺失，使用测试 Fake 仅用于测试；开发 UI 显示“未配置”，不能伪装真实结果。
6. 更新 OpenAPI、Migration、README 或 Runbook 中受影响部分。
7. 不得擅自增加本文未要求的计费、社交、移动端等功能。

### 26.3 外部依赖不可用时

- Provider 接口和真实 Adapter 仍需完成。
- 测试使用确定性 Fake Adapter，并明确位于 `tests/fakes`。
- Production 配置缺失时返回 `PROVIDER_NOT_CONFIGURED`，UI 显示配置入口。
- 不能把 Fake Adapter 作为 production 默认值。

### 26.4 交付仓库结构

```text
ai-researcher/
  frontend/
  backend/
  infra/
    compose/
    nginx/
    observability/
  docs/
    architecture.md
    api.md
    security.md
    runbooks/
  scripts/
  docker-compose.yml
  .env.example
  Makefile (or equivalent cross-platform task runner)
  README.md
```

README 至少包含：前置条件、配置、启动、Migration、Seed、测试、常见故障、备份恢复入口。

---

## 27. 最终交付物清单

- [ ] React/TypeScript 完整前端及生产构建配置。
- [ ] FastAPI 完整后端、Celery Worker 与隔离 Runner 适配器。
- [ ] PostgreSQL Migration 和确定性 Demo Seed。
- [ ] Redis、MinIO、Neo4j、Milvus 集成及投影重建命令。
- [ ] 所有本文 API 的 OpenAPI 文档和前端类型。
- [ ] 两张基准页面及其所有真实功能入口。
- [ ] 文献、Evidence、实验、Agent、写作、审批的纵向闭环。
- [ ] Docker Compose、环境变量示例、健康检查和初始化流程。
- [ ] Unit、Integration、E2E、Visual、Security 测试。
- [ ] 日志、指标、Trace、审计和基础 Dashboard。
- [ ] 架构、安全、操作、备份恢复和故障处理文档。
- [ ] 本文第 23 节签字式验收结果，不得只提供主观演示结论。

---

## 28. 最终原则

AI-Researcher 的页面只是研究事实、任务和证据链的可视化入口。实现时始终保证：

```text
每一个数字都有查询来源；
每一个状态都有状态机；
每一个按钮都有权限、接口和结果；
每一个 Agent 输出都有来源、版本和预算；
每一个结论都能追溯到文献或实验；
每一个文件和实验都能用 Hash 复现；
每一次高风险改变都能审批和审计；
每一个失败都可观察、可解释、可重试。
```

只有达到以上标准，交付物才是一个真实可用的自动科研平台，而不是外观相似的静态 Dashboard。
