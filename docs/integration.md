# 通用集成指南 / Generic Integration Guide

这个项目不是某一个模型、某一个 IDE 或某一个 agent 框架专用的。它的核心由两部分组成：

- `skills/qing-li-dian-nao/SKILL.md`
  负责定义安全工作流、风险边界和交互要求。
- `skills/qing-li-dian-nao/scripts/cleanup_scan.py`
  负责执行本地只读扫描，输出 Markdown 和 JSON 报告。

## 适合接入的工具

- AI 编程助手
- 本地 agent / automation runner
- IDE 内置 AI 工作流
- slash command / prompt template / workflow template
- 任何支持本地 Shell、Python、PowerShell 的桌面工具

## 最小接入要求

你的工具至少需要做到：

1. 能读取或注入 `SKILL.md` 中的规则。
2. 能在本地执行 `cleanup_scan.py`。
3. 能把扫描结果返回给用户，而不是只给出猜测。
4. 能在删除、移动、改配置前暂停并明确确认。

## 推荐接入方式

### 方式一：把 SKILL.md 当作技能说明

适用于支持 skill、tool preset、system prompt 或 workflow template 的工具。

- 导入 `SKILL.md`
- 给它本地命令执行能力
- 将 `cleanup_scan.py` 暴露为可调用脚本

### 方式二：只复用扫描器

适用于不支持技能系统，但支持终端命令的工具。

```powershell
$env:PYTHONUTF8 = "1"
python ".\skills\qing-li-dian-nao\scripts\cleanup_scan.py" `
  --include-common --include-known `
  --output "D:\cleanup-reports"
```

然后把生成的 Markdown/JSON 报告交给你的 agent 或用户界面继续分析。

## 推荐的命令映射

- `/清理电脑`
- `/扫描磁盘占用`
- `/找重复文件`
- `/整理下载目录`
- `/排查C盘爆满`

这些命令名只是示例，不是协议要求。

## 集成时不要做的事

- 不要默认上传文件内容、文件名清单或目录树到远程模型
- 不要跳过只读扫描，直接做删除/移动
- 不要把“全部清理”当成永久删除授权
- 不要把系统目录、项目源码、数据库、虚拟机镜像当成低风险对象

## 兼容性说明

- 仓库内的 `agents/openai.yaml` 只是一个 OpenAI 兼容元数据示例，不代表项目依赖 OpenAI 才能运行。
- 仓库内保留了 Codex 安装示例，是为了方便现成用户接入，不代表项目只适用于 Codex。
- 如果你的工具有自己的 skill 目录、prompt 仓库或工作流配置目录，只需要把 `SKILL.md` 和脚本映射进去即可。
