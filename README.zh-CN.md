# recursive-closure-skill

[English](README.md) | [中文](README.zh-CN.md)

一个 AI 编程 Agent 技能，通过递归闭环、严格成功检查、分动作 Worker 指令和文件系统台账，解决复杂问题。

支持所有支持技能/指令文件的 AI 编程 Agent（Claude Code、Codex CLI 等）。

![Demo](assets/demo.gif)

![Dashboard](assets/dashboard.png)

## 安装

### 让你的 Agent 帮你装

把下面这句话粘贴给你的 AI 编程 Agent（Claude Code 等）：

> Clone https://github.com/chriswangcq/recursive-closure-skill and install it to your skills directory.

Agent 会执行类似这样的命令：

```bash
git clone https://github.com/chriswangcq/recursive-closure-skill ~/.claude/skills/recursive-closure-skill
```

然后在任意对话中用 `/recursive-closure-skill` 调用。

### Claude Code（CLI / 桌面端 / Web）

手动安装 — 克隆或软链到 skills 目录：

```bash
# 方式 A：直接克隆
git clone https://github.com/chriswangcq/recursive-closure-skill ~/.claude/skills/recursive-closure-skill

# 方式 B：软链本地仓库
git clone https://github.com/chriswangcq/recursive-closure-skill /path/to/recursive-closure-skill
ln -s /path/to/recursive-closure-skill ~/.claude/skills/recursive-closure-skill
```

然后在任意对话中用 `/recursive-closure-skill` 调用。

Claude Code 提供 CLI（`npm install -g @anthropic-ai/claude-code`）、桌面端（macOS / Windows）、Web 端（claude.ai/code）以及 IDE 扩展（VS Code、JetBrains）。

### Codex CLI（OpenAI）

将 `SKILL.md` 内容加入 Codex Agent 指令：

```bash
# 方式 A：通过指令文件引用
codex --instructions /path/to/recursive-closure-skill/SKILL.md

# 方式 B：加入项目配置
cp /path/to/recursive-closure-skill/SKILL.md .codex/instructions/recursive-closure-skill.md
```

安装 Codex CLI：`npm install -g @openai/codex`

### Cursor

添加为 Cursor 规则：

1. 打开 Cursor Settings（Cmd+Shift+J / Ctrl+Shift+J）
2. 进入 **Rules** → **Project Rules**
3. 新建规则文件 `.cursor/rules/recursive-closure-skill.mdc`，粘贴 `SKILL.md` 内容

或在 `.cursorrules` 文件中引用 skill 目录。

### Windsurf

添加为 Windsurf 规则：

1. 在项目根目录创建 `.windsurfrules`（或全局规则 `~/.windsurf/rules/`）
2. 粘贴 `SKILL.md` 内容

### Cline（VS Code 扩展）

添加为自定义指令：

1. 在 VS Code 中打开 Cline 设置
2. 进入 **Custom Instructions**
3. 粘贴 `SKILL.md` 内容

或在项目根目录创建 `.clinerules` 文件并粘贴内容。

### Roo Code（VS Code 扩展）

添加为自定义指令：

1. 在 VS Code 中打开 Roo Code 设置
2. 进入 **Custom Instructions**
3. 粘贴 `SKILL.md` 内容

或创建 `.roo/rules/recursive-closure-skill.md` 文件。

### 其他 Agent

将你的 Agent 指令/技能加载器指向本仓库的 `SKILL.md`。本技能与 Agent 无关 — 任何能遵循结构化指令并运行 shell 命令的 Agent 都可以驱动台账循环。

## 概述

核心循环：创建问题 → 创建并定义 schema-v6 方案工单 → 将工单分类为 `one_go` 或 `split` → 执行或递归拆分子问题 → 记录结果 → 仅通过 `check_success` 关闭原始问题。

`one_go` 表示在检查前进行一次有边界的执行尝试，而非保证一次成功。只有工作确实小、具体、低风险且可立即验证时才应使用。执行过程中，`one_go` 工单可能在发现需要的子程序时派生阻塞性运行时子问题。部分完成或失败的尝试同样记为结果；`check_success` 在存在缺口时创建后续跟进问题。

本仓库刻意不支持旧版工单字段（如 `objective`、`scope`、`expected_result`）；台账脚本会拒绝非 v6 状态。请删除或重新初始化旧台账，而非迁移。

每个问题、工单、结果和检查都写为 Markdown body 文件。`state.json` 存储 ID、状态和关系；Markdown 存储语义内容。

## 职责划分

系统有四个角色：

- **状态机**：CLI 自动机，状态转换护栏，关系检查器，审计台账。
- **Root Agent**：循环驱动者，调用 `next`、分派当前动作、记录输出、推进闭环。
- **Worker Agent**：执行者，处理当前 `next_instruction` 的具体工作。
- **Markdown body**：工单、结果、检查和问题包的丰富语义内容。

目前 Root Agent 和 Worker Agent 通常是同一个 LLM Agent。角色在概念上分离，以便未来将 `next_instruction` 工作分派给独立 Agent 而不需要修改状态机。

Agent 始终向 CLI 请求下一步：

```bash
scripts/ledger.py next
```

`next` 返回短目标、边界、命令提示和匹配的 `references/workers/*.md` 指令文件。它调度可运行前沿叶节点：有未关闭子问题或跟进问题的父问题会等待子问题关闭。然后 Root Agent 执行或分派该 `next_action`，通过 CLI 记录 Worker Agent 输出，再次调用 `next`。

查看实时仪表板：

```bash
node scripts/render-dashboard.mjs --workspace /path/to/workspace
```

启动 HTTP 服务器，自动打开浏览器，台账状态变更时实时刷新。

## Root Agent 职责

Root Agent 负责编排：

- 运行 `scripts/ledger.py next`。
- 读取 `next_action` 和 `next_instruction`。
- 将工作分派给自己或 Worker Agent。
- 通过 CLI 记录 Worker 输出。
- 每次状态变更动作后再次运行 `next`。
- 持续直到 `next_action=none`，然后验证/渲染/报告状态。

## Worker Agent 职责

Worker Agent 处理需要理解、判断或实际执行的工作。Worker 指令按 `next_action` 精确拆分，使 Worker 专注于单项工作而无需理解整个状态机。

以 `references/workers/index.md` 为索引：

| next_action | Worker 指令 |
| --- | --- |
| `create-solution-ticket` | `references/workers/create-solution-ticket.md` |
| `define-ticket` | `references/workers/define-ticket.md` |
| `classify-ticket` | `references/workers/classify-ticket.md` |
| `execute-ticket` | `references/workers/execute-ticket.md` |
| `split-ticket` | `references/workers/split-ticket.md` |
| `record-result` | `references/workers/record-result.md` |
| `check-success` | `references/workers/check-success.md` |
| `unblock-or-report` | `references/workers/unblock-or-report.md` |
| `none` | `references/workers/none.md` |

Worker Agent 的工作包括：

- 编写方案工单：问题定义、拟议方案、验收标准、验证计划、风险和假设。
- 将工单分类为 `one_go` 或 `split`，除非明确是一次有边界的尝试，否则倾向 `split`。
- 执行 one-go 工单，在发现阻塞性子程序时派生运行时子问题。
- 将复杂工单拆分为计划时子问题。
- 遵循递归等待：先解决未关闭的子问题或跟进问题，再记录父级结果或检查。
- 将执行结果汇总为 result body。
- 以审查者身份运行 `check_success`：编写证据、标准映射、执行映射、压力测试、残余风险和缺口。对 `one_go` 结果施加更高的举证标准。

关键边界：Worker Agent 只做当前 `next_action`，不选择下一个状态机步骤——那是 Root Agent 加 CLI 的职责。

## CLI 自动机逻辑

CLI 掌管 Agent 不得自行发挥的规则：

- 分配 ID：`Pxxx`、`Txxx`、`Rxxx`、`Cxxx`。
- 返回短 `next_instruction` 分派文本并指向匹配的 Worker 指令文件。
- 强制工单流程：`created -> defined -> classified -> executing/splitting -> done`。
- 工单没有 `blocked`；任何完成的尝试记录结果后变为 `done`。
- 强制问题流程：`todo/doing/checking/followup/done/blocked`。
- 每个问题只有一个工单；后续尝试必须是子问题或跟进问题。
- 已完成的问题是终态，除非未来有显式重开命令。
- 限制公开 `set-status` 只用于准备性操作；终态由 `result` 和 `check` 写入。
- 从问题状态派生台账状态；不存储顶层台账状态字段。
- 所有问题、工单、结果和检查写入都要求 Markdown body 文件。
- 拆分子问题必须来自 `create-problem --from-ticket --mode split --from-file`；跟进问题仅由 `check --status not_success --followup-from-file` 创建。
- 运行时派生子问题必须来自 `create-problem --from-ticket --mode spawn --from-file`（在 one_go 工单执行期间）。
- 工单的所有子问题关闭前，该工单不能记录汇总结果。
- 防止并行跟进扇出；先解决当前跟进问题再创建新的。
- 要求 `check --status success|not_success` 引用显式 `--result` ID。
- 检查结果 ID 限制为当前问题结果加返回的跟进结果。
- 仅允许通过成功检查将问题标记为 `done`。
- 验证状态/body/路径/关系一致性并渲染派生视图。

总之：Root Agent 驱动循环，Worker Agent 生产内容和证据，CLI 决定每一步操作是否合法。

## 快速开始

```bash
# 创建根问题 body
cat > problem.md <<'EOF'
# 重新设计认证模块

## Problem

认证模块将会话管理与令牌验证混在一起...

## Success Criteria

- 会话和令牌逻辑已分离
- 所有现有测试通过
EOF

# 初始化台账
scripts/ledger.py init --from-file problem.md

# 进入 next 驱动循环
scripts/ledger.py next
```

然后遵循返回的 `next_action`。阅读引用的 `references/workers/*.md` 文件了解 Worker 行为，执行该单项动作，通过 CLI 记录结果，再次运行 `scripts/ledger.py next`。

## 使用方法

### 调用技能

在 Claude Code 中直接对话调用：

```
/recursive-closure-skill 重新设计认证模块，分离会话和令牌逻辑
/recursive-closure-skill --effort high 修复所有失败的集成测试
/recursive-closure-skill --effort extra-high --language zh 审计支付系统
```

对于其他 Agent，确保 `SKILL.md` 已加载为指令，然后要求 Agent 解决复杂问题。Agent 会自动使用台账 CLI。

### Next 驱动循环

核心工作流是 `scripts/ledger.py next` 驱动的循环：

```
init → create-solution-ticket → classify-ticket → execute/split → record-result → check-success → done
```

每次 `next` 调用返回要执行的确切动作、相关问题/工单上下文和 Worker 指令文件指针。Agent 执行该单项动作，记录输出，再次调用 `next`。

### 管理台账

```bash
# 列出当前工作区的所有台账
scripts/ledger.py list

# 切换到指定台账
scripts/ledger.py use L20260518-001

# 查看当前台账状态
scripts/ledger.py status

# 验证台账一致性
scripts/ledger.py validate

# 渲染派生视图
scripts/ledger.py render
```

### 仪表板

查看任意包含 `.complex-problems` 的工作区的交互式仪表板：

```bash
node scripts/render-dashboard.mjs --workspace .
# 自动打开浏览器，台账状态变更时实时刷新
```

仪表板包含问题树、进度环、D3 力导向图、时间线、暗色模式和 WebSocket 实时刷新。

## 配置

### 力度级别

通过 `--effort` 控制分类、检查、拆分和执行的严格程度：

```bash
scripts/ledger.py init --from-file problem.md --effort high
```

| 级别 | 行为 |
| --- | --- |
| `low` | 倾向 `one_go`，轻量检查，粗粒度拆分 |
| `medium` | 默认。平衡的分类和检查 |
| `high` | 倾向 `split`，深入检查，细粒度子问题 |
| `extra-high` | 全部拆分，完整审计检查，单一职责子问题 |

### 语言

控制 body 内容的语言（标题、描述、标准、证据）：

```bash
scripts/ledger.py init --from-file problem.md --language zh
```

CLI 标志和字段名始终为英文；只有 Markdown body 内容使用指定语言。

## 平台说明

台账使用 `fcntl.flock` 进行文件级锁定，防止并发写入损坏 `state.json`。这是 **Unix 专用** API — 台账在 macOS 和 Linux 上运行。目前不支持 Windows。

更详细的设计原理见 `DESIGN.md`。
