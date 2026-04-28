# 清理电脑研究综合

## 参考项目提炼

- hyperfield/ai-file-sorter：关键价值是本地优先、远程模型显式选择、分类/重命名前可审阅、dry run 预览、持久 undo 计划、分类白名单和冲突命名处理。
- QiuYannnn/Local-File-Organizer：关键价值是本地 Nexa 模型、按内容/日期/类型三种整理模式、默认先 dry run、输出拟议目录树、文件名清洗、冲突后缀。
- niuhai/skill-c-cleaner：关键价值是只读 C 盘分析、删除建议和迁移方案分离、覆盖系统隐藏占用、开发工具缓存、浏览器缓存、Docker/WSL、用户目录大文件。
- yunmaoQu/file-cleaner-pro：关键价值是重复文件/大文件/旧文件扫描、文件重要性建议、备份/恢复日志、安全配置、测试覆盖。
- steveleecode/Fathom：关键价值是自然语言查询、扫描上下文、按大小分组后 SHA-256 查重、删除走回收站、操作前展示候选。

## 综合原则

1. 扫描与执行分离：任何清理工具最危险的失败模式都是“发现即删除”。先生成计划，再执行确认过的子集。
2. 风险分级比“是否垃圾”更重要：同样是缓存，浏览器 profile、IDE 索引、Docker layer、pip wheel 的后果完全不同。
3. 可回滚优先：整理文件要有 undo plan；删除文件要进回收站或隔离区；配置迁移要记录旧值。
4. 本地隐私优先：目录清单本身也可能敏感，远程 AI 只能在用户明确允许后使用。
5. 使用工具原生命令：包管理器、Docker、Windows 组件存储都有自己的清理入口，优先于手删目录。

## 风险矩阵

低风险，通常可清理但仍需确认：用户临时目录、Windows Temp 中旧文件、缩略图/图标缓存、pip/npm/yarn/pnpm 缓存、已完成安装包残留、应用日志。

中风险，需要说明后果：浏览器缓存、IDE 索引缓存、旧下载文件、重复文件、旧压缩包、旧虚拟环境、conda/pip 包缓存、NuGet/Maven/Gradle/Cargo 仓库、回收站。

高风险，必须单独确认并建议备份：Docker Desktop 数据、WSL vhdx、虚拟机镜像、数据库文件、邮件/聊天记录、云同步目录、照片/视频原件、源码仓库、`AppData\Roaming` 配置。

禁止手工删除：`C:\Windows` 核心目录、`WinSxS`、`System Volume Information`、`Program Files`、`Program Files (x86)`、页面文件、注册表项、系统/应用正在使用的数据目录。

## 推荐报告结构

```text
1. 当前结论：磁盘空闲量、总扫描大小、最大占用来源、可安全释放估算
2. 低风险清理清单：路径、大小、建议命令、回滚方式
3. 需要确认清单：路径、大小、为什么不自动处理
4. 迁移建议：源位置、目标盘建议、配置方式、验证命令
5. 默认跳过目录：说明为何跳过，是否需要复扫
6. 不建议处理项：原因
7. 下一步：请用户选择编号，逐项执行并复扫
```

## Windows 重点类别

- 系统组件：用 DISM 分析组件存储，不手删 `WinSxS`。
- 休眠文件：只有用户明确不需要休眠/快速启动时才考虑 `powercfg /hibernate off`。
- 页面文件：不删除；如确需迁移，用系统设置，说明重启要求。
- 还原点：不要默认清空；优先限制最大占用或保留最新还原点。
- 更新缓存：确认系统不在更新中，再通过停止/启动 Windows Update 服务处理。
- 回收站：先列出体积和提醒检查，再清空。

## 开发者缓存迁移优先级

- npm：`npm config set cache "D:\dev-cache\npm"`，清理用 `npm cache verify` 或 `npm cache clean --force`。
- pnpm：`pnpm store prune`，迁移用 `pnpm config set store-dir "D:\dev-cache\pnpm-store"`。
- yarn：`yarn cache clean`，迁移用 `yarn config set cacheFolder "D:\dev-cache\yarn"`。
- pip：`pip cache dir` / `pip cache purge`，迁移用 `PIP_CACHE_DIR` 或 `pip.ini`。
- Cargo：迁移 `CARGO_HOME` 前先确认 Rust 工具链和项目依赖。
- Maven/Gradle/NuGet：清理会触发重新下载，企业内网/离线环境要谨慎。
- Docker/WSL：优先迁移磁盘镜像位置或导出/导入，不直接删除 vhdx。

## 扫描策略补充

- 大目录先做元数据扫描，不急着精确哈希；只有同大小候选明显时再启用 SHA-256。
- `node_modules`、`.git` 等目录默认可跳过以避免一次扫描被依赖树拖垮，但必须在报告中列出，不能静默漏掉。
- 高风险已知目录默认只列存在状态；需要测量时加显式开关，并在计划里说明只是测量，不代表建议清理。
- 输出目录优先非 C 盘；如果用户给了 C 盘输出路径，报告中记录提醒。
