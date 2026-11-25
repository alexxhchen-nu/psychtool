# ADR 0010：服务器/浏览器存储改用 SQLite（按个案隔离），JSON 工作区保留给 CLI/评测链路

日期：2026-11-24。状态：已确认（Alex 2026-11-24 答复技术设计 Q3）。

## 决策

服务器/浏览器路径（`psychtool-server` 及其 API、浏览器原型）的个案存储从 ADR 0005 的 JSON 文件工作区切换为**单个 SQLite 数据库**（标准库 `sqlite3`，无新增依赖）。**本 ADR 取代 ADR 0005 在应用存储上的地位**；JSON 工作区仍是 CLI / TUI / 评测 / judge / draft / export 链路的事实格式（见「仍然使用 JSON 的部分」）。

- 数据库位置：默认 `local-data/psychtool.db`，可用环境变量 `PSYCHTOOL_DB_PATH` 覆盖。
- 提供 `import-json <workspace-dir> [--db PATH]` CLI 命令，把 ADR 0005 JSON 工作区整体导入 SQLite（单事务，失败不落一行；拒绝覆盖已有个案）。`fixtures/case_a001` 为随仓库的合成导入样例。

## 理由

- 多案浏览器会话需要**结构性**个案隔离：文件方案靠目录约定，SQLite 用复合主键/外键在数据库层强制 `case_id` 边界（跨案引用直接违反约束）。
- 并发与崩溃恢复：WAL + `synchronous=FULL` 让断电/进程被杀后数据库自恢复，无需自造文件锁与恢复逻辑（现有 egress 锁语义平移到行级锁列）。
- 单文件、无服务进程、Python 标准库自带，延续 ADR 0002/0005「零重型依赖、可解释」的约束。

## 架构

### Schema 摘要（`PRAGMA user_version` 管理版本）

| 表 | 主键 | 说明 |
|---|---|---|
| `cases` | `case_id` | 个案登记（含 data_tier、created_at） |
| `known_names` | `(case_id, name)` | 人工登记的标识符（脱敏用） |
| `materials` | `(case_id, material_id, version)` | 材料元数据，版本不可变 |
| `passages` | `(case_id, material_id, version, passage_id)` | 材料段落；外键指向 materials |
| `claims` | `(case_id, claim_id, version)` | 候选/已接受陈述；**复合外键 `(case_id, source_document_id, source_version, source_passage_id)` → passages**，跨案来源在数据库层不可能 |
| `sections` | `(case_id, template_id, section_id, version)` | 段落草稿，版本不可变 |
| `egress_requests` | `(case_id, request_id)` | 出闸请求全生命周期；status 受 CHECK 约束（与 `EgressStatus` 枚举一致，有测试保证不漂移） |

### 隔离如何强制

1. **按个案仓储（per-case repository）**：`SqliteStore.case(case_id)` 返回绑定单一 `case_id` 的 `CaseStore`，所有 SQL 均带 `case_id = ?` 谓词，参数化查询（标识符仅来自固定白名单）。
2. **复合主键/外键**：所有实体主键以 `case_id` 开头；claims→passages 的复合外键使「A 案陈述引用 B 案段落」在 INSERT 时即被 `IntegrityError` 拒绝，不依赖应用层自觉。
3. **API 层**：`_case()` 绑定器把未知个案映射为 404、非法 id 映射为 400；对抗性测试覆盖 `../x`、`A' OR '1'='1`、`%`、`_` 等敌意输入，以及跨案 claim/egress/section 访问全部 404。

### 持久化设置

- `PRAGMA journal_mode=WAL`、`PRAGMA synchronous=FULL`、`PRAGMA foreign_keys=ON`。
- 每个连接线程局部；多步写入包在嵌套 `transaction()` 中。
- 掉电测试：子进程写入中被 SIGKILL，父进程验证 `PRAGMA integrity_check` 通过、无半事务行、库仍可写。

### 出闸锁的平移

ADR 0005 时代基于文件锁的 egress 发送/状态迁移互斥，改为 `egress_requests` 行内锁列（`send_lock_owner` / `transition_lock_owner`），owner 校验释放；缺失请求行在取锁时即 404。同一套 egress 安全管线（`EgressStore` 协议 + `JsonDirStore` + `SqliteGatewayStore`）同时服务 JSON 与 SQLite 两种后端，安全逻辑不分叉。

## 仍然使用 JSON 的部分

CLI / TUI / `eval` / `judge` / `draft` / `export` 链路继续使用 ADR 0005 的 JSON 工作区，因为：

- 评测与 fixtures 与 JSON 同源（ADR 0005 的既有理由仍成立）：可直接 diff、git 可见、损坏可手工修复。
- 这些链路是单案、单进程、顺序执行，用不到数据库的并发与结构约束；迁移只会增加无谓改动面。
- `import-json` 作为单向桥：JSON 工作区可随时进入 SQLite 应用存储，反向不需要。

## 后果

- 服务器默认写 `local-data/psychtool.db`（已在 `.gitignore`）；浏览器原型与 CLI 的存储从此分离，互不影响。
- SPA 前端路由回退不得应答 `/api/*`：未知 API 路径返回 JSON 404（有测试），避免构建产物存在时未知 API 路径被 index.html 以 200 吞掉。
- Playwright e2e 每次运行使用全新临时数据库（`mkdtempSync` + `PSYCHTOOL_DB_PATH`），并钉死 `PSYCHTOOL_TRANSPORT=fake`、`PSYCHTOOL_DATA_TIER=synthetic`。
- 后续：若 CLI 链路也要统一进 SQLite，另行评估；本 ADR 不预设该迁移。
