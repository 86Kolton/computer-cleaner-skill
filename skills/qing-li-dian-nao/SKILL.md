---
name: qing-li-dian-nao
description: "安全清理电脑、清理C盘、释放磁盘空间、整理下载/桌面/文档、查找大文件/旧文件/重复文件、迁移开发工具缓存、分析Docker/WSL/浏览器/包管理器缓存时使用。用户输入“/清理电脑”“清理电脑”“电脑空间不够”“C盘爆了”“帮我整理文件”“找重复文件”等都应触发。默认只读扫描，生成分级清理/迁移方案，任何删除、移动、改配置前必须逐项确认并保留回滚路径。"
---

# 清理电脑

## 核心契约

- 先证据、后动作。除非用户明确只要建议，否则先做只读扫描，拿到体积、路径、时间、重复候选、风险等级后再判断。
- 默认不删除、不移动、不改配置。清理动作必须在用户确认具体项目后执行；宽泛确认如“都清了”仍要拆成项目清单再确认。
- 优先使用可回滚方式：回收站、非 C 盘隔离区、备份清单、undo/manifest。不要默认永久删除或“安全擦除”。
- 对 C 盘尤其保守。系统目录、程序目录、页面文件、还原点、WSL/Docker 镜像、云同步目录、个人照片/文档必须人工确认。
- 隐私优先。不得把文件内容、文件名清单、截图或目录树上传到远程 AI/API，除非用户明确同意；默认只在本地分析元数据。
- 产物放在非 C 盘优先：当前工作区、用户指定非 C 路径、`$CODEX_HOME\.tmp`，或可用的非 C 盘临时报告目录。扫描报告很小也尽量遵守。

## 工作流

1. 判定目标：释放空间、整理文件、找重复、迁移缓存、排查 C 盘异常占用，或组合目标。
2. 确定范围：用户给了路径就用该路径；只说“电脑/C盘”时，先扫描当前用户常见目录和已知缓存，不要直接全盘深扫。
3. 运行只读扫描脚本：

```powershell
$env:PYTHONUTF8 = "1"
& "<python>" "<skill-dir>\scripts\cleanup_scan.py" `
  --include-common --include-known `
  --output "<非C盘报告目录>"
```

用可用 Python 替换 `<python>`；`<skill-dir>` 是当前 skill 的安装目录（例如 Windows 上的 `%USERPROFILE%\.codex\skills\qing-li-dian-nao`）。默认优先用 Codex bundled Python 或系统可用 Python。用户指定目录时加 `--root "D:\path"`，大范围首次扫描先不加 `--hash-duplicates`，等发现可疑重复候选后再对更窄范围做精确哈希。
默认会跳过系统目录以及 `node_modules`/`.git` 这类重型开发目录并在报告中列出；需要完整项目体积分析时再加 `--include-dev-heavy`。高风险已知位置只列存在状态，确需测量时再加 `--measure-high-risk-known`。

4. 生成行动计划，按收益和风险分组：
   - 可直接清理：临时目录、缩略图缓存、明确可重建的包管理器缓存。
   - 建议迁移：npm/pnpm/yarn/pip/Cargo/Maven/Gradle/NuGet、Docker/WSL 数据、下载目录归档。
   - 需要人工确认：重复文件、旧安装包、大型视频/压缩包、浏览器缓存、回收站。
   - 不建议处理：系统核心、个人资料、项目源码、云同步目录、数据库/虚拟机镜像、页面文件。
5. 执行前给出三件事：将处理的确切路径、预计释放空间、回滚办法。没有这三件事不执行。
6. 执行后复扫或至少重查目标目录/磁盘空闲空间，报告释放量、失败项和残余风险。

## 安全执行规则

- 删除类动作优先用回收站；没有回收站能力时，移动到非 C 盘隔离区：`cleanup-quarantine\<timestamp>\`，同时写 `manifest.jsonl` 记录原路径、大小、mtime、hash(可行时)。
- 对“默认跳过目录”不要猜测大小；如它们可能是主要占用，先用更窄范围和 `--include-dev-heavy` 复扫。
- 对重复文件只自动标记，不自动删除。建议保留：路径更短、mtime 更新、位于正式资料库/项目目录中的副本；删除候选必须逐项确认。
- 对浏览器缓存优先指导用户用浏览器内置清理入口；直接删除 profile 目录前必须说明可能丢失登录态、IndexedDB、扩展状态。
- 对开发工具缓存优先使用工具命令：`npm cache verify/clean`、`pnpm store prune`、`yarn cache clean`、`pip cache purge`、`cargo cache`、`gradle --stop` 后处理缓存。
- 对 Docker/WSL 先用 `docker system df`、`wsl --list --verbose`、实际 vhdx 大小分析；`docker system prune -a`、WSL 导出/导入/注销都属于高风险，必须单独确认。
- 对 Windows 组件只用官方清理通道：`Dism /Online /Cleanup-Image /AnalyzeComponentStore` 先分析，再决定 `StartComponentCleanup`。不要手删 `WinSxS`。
- 禁止对未枚举确认的路径运行递归删除。尤其不要对根目录、用户目录、`AppData`、`Program Files`、`Windows`、云盘同步根目录做通配递归删除。

## 整理文件模式

当用户想“整理下载/桌面/文档/图片”时：

- 先生成预览树，不直接移动。
- 优先按现有目录习惯、扩展名、日期、文件名关键词分类；只有用户同意时才读取文档内容或使用远程 AI。
- 重命名建议必须清洗非法字符、限制长度、避免覆盖，并保留原扩展名。
- 默认选择“复制/硬链接到整理目录”或“移动并写 undo 计划”二选一；不确定时选复制/硬链接预览，减少误伤。
- 输出清单要能让用户一眼看出：源路径、目标路径、分类原因、是否重命名、冲突处理。

## 资源

- `scripts/cleanup_scan.py`：标准库只读扫描器，输出 Markdown + JSON 报告。
- `references/research-synthesis.md`：从参考项目提炼的设计原则、风险矩阵和清理类别。需要深度方案或遇到边界情况时读取。
