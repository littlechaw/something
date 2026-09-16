# 先知消息研究与复盘系统

本项目用于从本地钉钉导出“先知”消息，并通过统一的 AI 工作流完成日常复盘、历史关注点记录、标的跟踪和月度主题沉淀。

项目的目标不是照单交易，而是把分散消息整理成 **可阅读、可追踪、可复盘** 的研究资料。

## 文档导航

| 文档 | 面向对象 | 权威内容 |
| --- | --- | --- |
| `README.md` | 人类使用者 | 项目入口、目录导航和最短日常流程 |
| `AGENTS.md` | Codex 等 AI 工具 | 通用协作规则、任务识别和工作流路由 |
| `CLAUDE.md` | Claude Code | 导入 `AGENTS.md`，不单独维护规则 |
| `finance/先知/README.md` | 人类与 AI | 研究方法论、泊松过程、主题分类和交易手册 |
| `finance/先知/工作流.md` | 执行任务的 AI | 先知消息处理、归档、文件更新和校验规则 |
| `tools/README.md` | 人类与执行工具的 AI | 导出、阅读器、同步、部署和排障说明 |

同一事项只在对应权威文档中维护。发生表述不一致时，专项任务以 `finance/先知/工作流.md` 为准，项目通用行为以 `AGENTS.md` 为准。

## 目录结构

```text
exports/YYYY-MM-DD/先知/       钉钉原始消息、图片和缩略图，仅保留在本地或服务器
finance/先知/reviews/daily/    每日消息复盘
finance/先知/reviews/articles/ 公众号文章复盘
finance/先知/reviews/weekly/   周度、阶段和月度合并复盘
finance/先知/topics/           月度沉淀后的长期主题
finance/先知/跟踪台账.csv      标的持续跟踪台账
finance/先知/验证清单.md       历史关注清单，文件名为兼容现有引用而保留
tools/                          导出、阅读、同步和部署工具
```

## 最短日常流程

### 1. 导出当天消息

```bash
cd ~/Downloads/demo/something
python3 tools/export.py "$(date +%F)"
```

完整依赖、指定日期、批量导出和异常处理见 `tools/README.md`。

### 2. 让 AI 执行正式工作流

在 Codex 或 Claude Code 中输入：

```text
请按先知工作流处理今天的导出消息。
```

AI 应通过 `AGENTS.md` 进入 `finance/先知/工作流.md`，不需要在提示词中重复完整规则。

### 3. 检查生成结果

```bash
git status --short
git diff -- finance/先知
```

每日总结只生成或更新：

- `finance/先知/reviews/daily/` 下的对应复盘；
- `finance/先知/跟踪台账.csv`；
- 按需更新的历史关注清单 `finance/先知/验证清单.md`。

**每日总结不更新 `finance/先知/主题索引.md`，也不更新 `finance/先知/topics/`。** 这两部分只在月度合并复盘后更新。

### 4. 本地阅读

```bash
node tools/xianzhi-reader/server.mjs
```

默认访问 `http://127.0.0.1:8787`。阅读器索引、端口、服务器同步和部署说明见 `tools/README.md`。

### 5. 提交研究文件

```bash
git add finance/先知
git commit -m "docs(先知): 更新$(date +%F)消息复盘"
```

提交信息使用 Conventional Commits，摘要使用中文。

## 核验与写入边界

- 钉钉日总结默认不联网核验。
- `finance/先知/验证清单.md` 只作为历史关注清单，不记录“已验证、部分验证、未验证”等状态。
- 用户明确要求核验时，按用户当次要求执行。
- 用户只要求核验、没有要求写入时，核验结果只在当次回复中呈现。
- 用户要求写入但没有指定位置时，更新对应的现有复盘文件；若找不到对应文件，必须先询问，不得擅自新建。

## 安全边界

- `client_config.json`、`.dec_data/`、`exports/` 和阅读器索引只保留在本地或指定服务器，不进入 Git。
- 原始导出可能包含聊天记录、图片和身份信息，同步或分享前应确认内容范围。
- 圈内观点只作为研究材料，不直接改写成确定事实或投资指令。
