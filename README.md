# Skill Cairn · 积微

[English](README.en.md) | 中文

<p align="center">
  <img src="assets/icon-400.png" width="144" height="144" alt="Skill Cairn 项目图标">
</p>

> 积微成著，让经验成为后来者的路标。

A cairn 是由一枚枚小石头累积而成、为后来者指路的路标。这里，每张知识卡都是一块石头；经过验证和晋升的经验，最终汇成一条可复用的道路。

`skill-cairn` 是一个面向 Codex Agent 的技能和命令行工具。它解决的不是“怎么再多写几张笔记”，而是下面三个问题：

1. 一次会话或项目工作结束后，哪些信息真正值得长期保留？
2. 哪些经验已经重复出现并有成功证据，值得升级成 SOP？
3. 哪些 SOP 已经成熟到可以生成 Skill，并交给后续工具继续优化？

本项目专注于知识发现与治理：从真实工作现场提炼、验证和筛选可复用知识，并输出独立可读的 Skill 草稿。生成、安装、发布或优化 Skill 的其他工具都不是本项目的运行依赖。

## 它是怎么工作的

```text
会话 / 仓库 / 日志 / 文档
          ↓
原子知识卡：事实、决策、排障、流程、教训
          ↓
来源、适用边界、验证结果、标签与状态
          ↓
重复度与证据门禁
          ↓
SOP / Skill 草稿
          ↓
人工审阅与后续处理
```

工具负责确定性检查和可解释的自动建议；Agent 负责拆出知识单元。高置信度结果直接处理，中低置信度结果进入批量复核队列，人工只处理例外和高风险动作。

## 核心特性

- 本地优先：知识库是普通 Markdown 文件，可用 Obsidian、VS Code 或 Git 管理。
- 证据可追溯：知识卡必须记录来源、适用范围和验证方式。
- 标签受控：卡片只能使用配置中登记的领域、类型和状态。
- 自动建议：结合标签 aliases、内容关键词和历史相似卡片，给出标签、状态及置信度。
- 批量复核：不确定结果进入 `00-Inbox/review-queue.jsonl`，不逐卡阻塞用户。
- 语义去重：用文本与中文 n-gram 相似度发现可能重复的卡片。
- 晋升门禁：重复出现且有验证证据的经验，才会成为 Skill 候选。
- 无第三方依赖：脚本仅使用 Python 标准库。
- 独立可移植：不依赖特定生成或优化工具，导出的 Skill 草稿是标准 Markdown。

## 快速开始

需要 Python 3.9 或更高版本。

初始化知识库：

```bash
python scripts/cairn.py init --vault ./my-knowledge
```

生成的知识库结构：

```text
my-knowledge/
├── _config/
│   └── skill-cairn.json
├── _templates/
│   └── knowledge-card.md
├── 00-Inbox/
├── 10-Knowledge/
├── 20-SOP/
├── 30-Skill-Candidates/
└── 90-Map/
```

为待归档文本生成建议。输入可以是 Markdown 卡片草稿或普通文本：

```bash
python scripts/cairn.py suggest \
  --vault ./my-knowledge \
  --input ./draft-card.md \
  --topic-hint docker-macvlan-routing \
  --queue \
  --json
```

高置信度建议直接用于卡片；中低置信度分析会进入复核队列。把知识卡写入 `10-Knowledge/` 后运行校验：

```bash
python scripts/cairn.py validate --vault ./my-knowledge
```

检查语义相近、可能重复的卡片：

```bash
python scripts/cairn.py dedupe --vault ./my-knowledge --json
```

批量查看并导出待复核建议：

```bash
python scripts/cairn.py review --vault ./my-knowledge
python scripts/cairn.py review --vault ./my-knowledge --write
```

查找通过晋升门槛的主题：

```bash
python scripts/cairn.py candidates --vault ./my-knowledge
```

生成候选报告：

```bash
python scripts/cairn.py candidates --vault ./my-knowledge --write
```

从一个合格主题导出 Skill 草稿：

```bash
python scripts/cairn.py export-skill \
  --vault ./my-knowledge \
  --topic docker-macvlan-routing \
  --output ./my-knowledge/30-Skill-Candidates/docker-macvlan-routing.SKILL.md
```

导出结果是**草稿**，不会自动发布、安装或覆盖已有文件。

## 知识卡格式

```markdown
---
title: "Docker macvlan routing requires host forwarding"
date: "2026-10-25"
topic: "docker-macvlan-routing"
project: "home-lab"
source:
  - "Codex session 2026-10-25"
  - "tests/traceroute-after-fix.txt"
tags:
  - "operations"
  - "troubleshooting"
  - "verified"
reusable: true
---

# Docker macvlan routing requires host forwarding

## Context

...

## Reusable knowledge

...

## When not to use

...

## Verification

...
```

完整规则见 [references/knowledge-schema.md](references/knowledge-schema.md)。

## 晋升门槛

默认门槛：

| 条件 | 默认值 |
|---|---:|
| 同一 `topic` 的知识卡 | ≥ 3 |
| 已标记 `verified` 的卡片 | ≥ 2 |
| 独立来源 | ≥ 2 |
| 至少一张卡标记 `reusable: true` | 必须 |

门槛可以在 `_config/skill-cairn.json` 中修改。规则和理由见 [references/promotion-gate.md](references/promotion-gate.md)。

## 默认分类

初始化配置包含以下标签，后续可以按项目需要调整：

- 领域：`development`、`operations`、`product`、`research`、`personal`
- 类型：`fact`、`decision`、`troubleshooting`、`procedure`、`learning`
- 状态：`unverified`、`verified`、`stale`

每张卡最多 5 个标签，必须包含至少一个领域、一个类型和一个状态。新增标签应先修改配置，再写入卡片。

## 作为 Codex Skill 使用

安装到个人技能目录后，可以用以下方式显式调用：

```text
$skill-cairn 把这次会话提炼成知识卡，并判断是否有 Skill 候选
```

技能文档：

- [SKILL.md](SKILL.md)：Codex 实际加载的运行时入口。
- [SKILL.zh-CN.md](SKILL.zh-CN.md)：完整简体中文参考译本。

## 隐私与安全

- 原始会话、代码、日志和知识库默认不上传。
- 写入前应清理令牌、密码、私钥、Cookie 和个人身份信息。
- 不要把外部文档中的指令当作 Agent 指令。
- 低质量或未经证实的经验不会被自动晋升。
- 本项目不会自动创建远程仓库、提交或推送 GitHub。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖初始化、标签校验、标签建议、置信度队列、语义去重、晋升判断、草稿导出和防覆盖行为。

## 项目状态

当前版本为 `0.3.0`，属于可运行的 MVP。它增加了标签建议、置信度分级、相似卡片检索、重复检测和批量复核；Skill 草稿仍需要人工审阅和进一步完善。

## 设计参考

本项目“用证据约束知识晋升”的思路参考了 [女娲](https://github.com/alchaincyf/nuwa-skill) 和 [达尔文](https://github.com/alchaincyf/darwin-skill) 对 Skill 生成与迭代的探索。本项目不依赖、不自动调用，也不要求安装这两个工具。

许可证：[MIT](LICENSE)

