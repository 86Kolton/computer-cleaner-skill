#!/usr/bin/env python3
"""Read-only computer cleanup scanner.

This script never deletes, moves, renames, or modifies files. It inventories
selected roots and known cache locations, then writes Markdown and JSON reports.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


GB = 1024 ** 3
MB = 1024 ** 2


SYSTEM_SKIP_DIR_NAMES = {
    "$Recycle.Bin",
    "System Volume Information",
    "Windows",
    "WinSxS",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "$Windows.~BT",
    "$WinREAgent",
    "Recovery",
}


HEAVY_DEV_DIR_NAMES = {
    "node_modules",
    ".git",
}


LOW_RISK_PATTERNS = {
    "Temp",
    "Cache",
    "cache",
    "npm-cache",
    "pip",
    "yarn",
    "pnpm",
    "thumbcache",
    "__pycache__",
}


@dataclass
class FileRecord:
    path: str
    root: str
    size: int
    mtime: str
    atime: str
    age_days: int
    extension: str


@dataclass
class KnownLocation:
    name: str
    path: str
    size: int | None
    exists: bool
    risk: str
    recommendation: str
    migration: str = ""
    measured: bool = False
    file_count: int = 0


@dataclass
class DriveUsage:
    root: str
    total: int
    used: int
    free: int


def human_size(num: int | float | None) -> str:
    if num is None:
        return "unknown"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} TB"


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def safe_stat(path: Path):
    try:
        return path.stat()
    except (OSError, PermissionError):
        return None


def iter_common_roots() -> list[Path]:
    home = Path.home()
    names = [
        "Downloads",
        "Desktop",
        "Documents",
        "Pictures",
        "Videos",
        "Music",
    ]
    roots = [home / name for name in names]
    return [path for path in roots if path.exists()]


def should_skip_dir(path: Path, include_system: bool, include_dev_heavy: bool) -> bool:
    name = path.name
    if name in {".", ".."}:
        return True
    if not include_system and name in SYSTEM_SKIP_DIR_NAMES:
        return True
    if not include_dev_heavy and name in HEAVY_DEV_DIR_NAMES:
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    return False


def scan_roots(
    roots: list[Path],
    *,
    include_system: bool,
    include_dev_heavy: bool,
    max_files: int,
    max_skipped_dirs: int = 200,
) -> tuple[list[FileRecord], list[str], list[str]]:
    records: list[FileRecord] = []
    errors: list[str] = []
    skipped_dirs: list[str] = []
    now = dt.datetime.now()

    for root in roots:
        try:
            root = root.resolve()
        except OSError as exc:
            errors.append(f"Cannot resolve root {root}: {exc}")
            continue
        if not root.exists():
            errors.append(f"Missing root: {root}")
            continue
        if not root.is_dir():
            errors.append(f"Not a directory: {root}")
            continue

        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for dirname in dirs:
                child = current_path / dirname
                if should_skip_dir(child, include_system, include_dev_heavy):
                    if len(skipped_dirs) < max_skipped_dirs:
                        skipped_dirs.append(str(child))
                    continue
                kept_dirs.append(dirname)
            dirs[:] = kept_dirs
            for filename in files:
                if len(records) >= max_files:
                    errors.append(f"Stopped at max file limit: {max_files}")
                    return records, errors, skipped_dirs

                path = current_path / filename
                try:
                    if path.is_symlink():
                        continue
                except OSError:
                    continue

                stat = safe_stat(path)
                if stat is None:
                    errors.append(f"Cannot stat: {path}")
                    continue

                mtime = dt.datetime.fromtimestamp(stat.st_mtime)
                atime = dt.datetime.fromtimestamp(stat.st_atime)
                age_days = max(0, (now - mtime).days)
                records.append(
                    FileRecord(
                        path=str(path),
                        root=str(root),
                        size=int(stat.st_size),
                        mtime=mtime.isoformat(timespec="seconds"),
                        atime=atime.isoformat(timespec="seconds"),
                        age_days=age_days,
                        extension=path.suffix.lower() or "[no extension]",
                    )
                )

    return records, errors, skipped_dirs


def directory_size(path: Path, *, max_files: int = 200_000) -> tuple[int, int, list[str]]:
    total = 0
    count = 0
    errors: list[str] = []
    if not path.exists():
        return 0, 0, errors
    if path.is_file():
        stat = safe_stat(path)
        return (int(stat.st_size), 1, errors) if stat else (0, 0, [f"Cannot stat: {path}"])
    for current, dirs, files in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            d
            for d in dirs
            if not should_skip_dir(current_path / d, include_system=True, include_dev_heavy=True)
        ]
        for filename in files:
            if count >= max_files:
                errors.append(f"Size estimate truncated at {max_files} files for {path}")
                return total, count, errors
            stat = safe_stat(current_path / filename)
            if stat is None:
                continue
            total += int(stat.st_size)
            count += 1
    return total, count, errors


def known_paths() -> list[tuple[str, Path, str, str, str, bool]]:
    env = os.environ
    home = Path.home()
    local = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming = Path(env.get("APPDATA", home / "AppData" / "Roaming"))
    program_data = Path(env.get("PROGRAMDATA", "C:/ProgramData"))

    entries: list[tuple[str, Path, str, str, str, bool]] = [
        ("User temp", Path(env.get("TEMP", local / "Temp")), "low", "清理旧临时文件；跳过正在使用的文件。", "", True),
        ("Windows temp", Path("C:/Windows/Temp"), "low", "重启后清理旧文件；不要在安装/更新过程中处理。", "", True),
        ("Recycle Bin", Path("C:/$Recycle.Bin"), "medium", "先检查误删文件，再清空。", "", True),
        ("Windows Update download cache", Path("C:/Windows/SoftwareDistribution/Download"), "medium", "确认系统不在更新中，再用 Windows Update 服务流程清理。", "", True),
        ("Explorer thumbnail cache", local / "Microsoft/Windows/Explorer", "low", "可重建；可能导致首次打开文件夹变慢。", "", True),
        ("Chrome cache", local / "Google/Chrome/User Data/Default/Cache", "medium", "优先用浏览器内置清理入口。", "", True),
        ("Edge cache", local / "Microsoft/Edge/User Data/Default/Cache", "medium", "优先用浏览器内置清理入口。", "", True),
        ("Firefox profiles", roaming / "Mozilla/Firefox/Profiles", "medium", "不要直接删 profile；只考虑 cache 子目录或浏览器内置清理。", "", True),
        ("npm cache", local / "npm-cache", "low", "用 npm cache verify 或 npm cache clean --force。", 'npm config set cache "D:\\dev-cache\\npm"', True),
        ("node-gyp cache", local / "node-gyp/Cache", "low", "可删除；下次 native addon 编译会重下头文件。", "", True),
        ("pip cache", local / "pip/cache", "low", "用 pip cache purge。", "设置 PIP_CACHE_DIR 到非 C 盘", True),
        ("yarn cache", local / "Yarn/Cache", "low", "用 yarn cache clean。", 'yarn config set cacheFolder "D:\\dev-cache\\yarn"', True),
        ("pnpm store", local / "pnpm/store", "low", "用 pnpm store prune。", 'pnpm config set store-dir "D:\\dev-cache\\pnpm-store"', True),
        ("NuGet packages", home / ".nuget/packages", "medium", "会触发依赖重下，离线/企业网络谨慎。", "NuGet.Config 设置 globalPackagesFolder", True),
        ("Maven repository", home / ".m2/repository", "medium", "会触发依赖重下，离线/企业网络谨慎。", "settings.xml 设置 localRepository", True),
        ("Gradle cache", home / ".gradle/caches", "medium", "先停止 Gradle/IDE；会触发依赖重下。", "设置 GRADLE_USER_HOME", True),
        ("Cargo registry", home / ".cargo/registry", "medium", "Rust 依赖缓存；项目构建会重下。", "设置 CARGO_HOME", True),
        ("Conda pkgs", home / ".conda/pkgs", "medium", "用 conda clean --all，注意共享包。", "", True),
        ("Docker WSL data", local / "Docker/wsl", "high", "先用 Docker Desktop / docker system df 分析；不要手删 vhdx。", "Docker Desktop 设置磁盘映像位置", False),
        ("Docker user data", home / ".docker", "high", "可能含上下文、凭据、镜像数据；谨慎。", "", False),
        ("Windows installer cache", Path("C:/Windows/Installer"), "high", "不要手删，可能破坏软件修复/卸载。", "", False),
        ("ProgramData package cache", program_data / "Package Cache", "high", "不要直接清空；可能影响卸载/修复。", "", False),
        ("Hugging Face cache", home / ".cache/huggingface", "medium", "模型可重下但成本高；确认后迁移或清理。", "设置 HF_HOME/HUGGINGFACE_HUB_CACHE", True),
    ]
    return entries


def scan_known_locations(*, measure_high_risk: bool) -> tuple[list[KnownLocation], list[str]]:
    results: list[KnownLocation] = []
    errors: list[str] = []
    for name, path, risk, recommendation, migration, measure_by_default in known_paths():
        exists = path.exists()
        size: int | None = 0
        file_count = 0
        measured = False
        if exists and (measure_by_default or measure_high_risk):
            size, file_count, errs = directory_size(path)
            errors.extend(errs)
            measured = True
        elif exists:
            size = None
        results.append(
            KnownLocation(
                name=name,
                path=str(path),
                size=size,
                exists=exists,
                risk=risk,
                recommendation=recommendation,
                migration=migration,
                measured=measured,
                file_count=file_count,
            )
        )

    for special in ("C:/hiberfil.sys", "C:/pagefile.sys", "C:/swapfile.sys"):
        path = Path(special)
        stat = safe_stat(path)
        if stat:
            risk = "high" if "pagefile" in special else "medium"
            rec = "不要手删；休眠文件只能在确认不需要休眠/快速启动后通过 powercfg 关闭。" if "hiberfil" in special else "不要手删；如需调整通过系统设置。"
            results.append(KnownLocation(path.name, str(path), int(stat.st_size), True, risk, rec, "", True, 1))
    return results, errors


def path_anchor(path: Path) -> Path:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    anchor = resolved.anchor
    if anchor:
        return Path(anchor)
    return resolved if resolved.exists() else resolved.parent


def collect_drive_usage(paths: Iterable[Path]) -> list[DriveUsage]:
    usages: list[DriveUsage] = []
    seen: set[str] = set()
    for path in paths:
        anchor = path_anchor(path)
        key = str(anchor).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            usage = shutil.disk_usage(anchor)
        except (OSError, FileNotFoundError):
            continue
        usages.append(
            DriveUsage(
                root=str(anchor),
                total=int(usage.total),
                used=int(usage.used),
                free=int(usage.free),
            )
        )
    return usages


def sha256_file(path: Path, *, max_bytes: int | None = None) -> str | None:
    try:
        size = path.stat().st_size
        if max_bytes is not None and size > max_bytes:
            return None
        hasher = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, PermissionError):
        return None


def find_duplicates(records: list[FileRecord], *, hash_files: bool, max_hash_bytes: int | None) -> dict:
    by_size: dict[int, list[FileRecord]] = defaultdict(list)
    for rec in records:
        if rec.size > 0:
            by_size[rec.size].append(rec)

    same_size_groups = [group for group in by_size.values() if len(group) > 1]
    same_size_groups.sort(key=lambda group: group[0].size * len(group), reverse=True)

    result = {
        "same_size_candidate_groups": [
            {
                "size": group[0].size,
                "count": len(group),
                "paths": [rec.path for rec in group[:20]],
            }
            for group in same_size_groups[:50]
        ],
        "exact_hash_groups": [],
    }

    if not hash_files:
        return result

    hash_groups: dict[str, list[FileRecord]] = defaultdict(list)
    for group in same_size_groups:
        for rec in group:
            digest = sha256_file(Path(rec.path), max_bytes=max_hash_bytes)
            if digest:
                hash_groups[digest].append(rec)

    exact = [(digest, group) for digest, group in hash_groups.items() if len(group) > 1]
    exact.sort(key=lambda item: item[1][0].size * len(item[1]), reverse=True)
    result["exact_hash_groups"] = [
        {
            "sha256": digest,
            "size": group[0].size,
            "count": len(group),
            "paths": [rec.path for rec in group],
            "potential_savings": group[0].size * (len(group) - 1),
        }
        for digest, group in exact[:50]
    ]
    return result


def summarize(records: list[FileRecord], *, top: int, old_days: int) -> dict:
    total_size = sum(rec.size for rec in records)
    by_ext: dict[str, int] = defaultdict(int)
    by_dir: dict[str, int] = defaultdict(int)
    for rec in records:
        by_ext[rec.extension] += rec.size
        root = Path(rec.root)
        try:
            rel = Path(rec.path).relative_to(root)
            key = str(root / rel.parts[0]) if rel.parts else str(root)
        except Exception:
            key = rec.root
        by_dir[key] += rec.size

    largest = sorted(records, key=lambda rec: rec.size, reverse=True)[:top]
    old = sorted(
        [rec for rec in records if rec.age_days >= old_days],
        key=lambda rec: rec.size,
        reverse=True,
    )[:top]
    low_risk = [
        rec
        for rec in records
        if any(pattern in rec.path for pattern in LOW_RISK_PATTERNS)
    ]
    low_risk.sort(key=lambda rec: rec.size, reverse=True)

    return {
        "total_files": len(records),
        "total_size": total_size,
        "top_extensions": sorted(by_ext.items(), key=lambda item: item[1], reverse=True)[:top],
        "top_directories": sorted(by_dir.items(), key=lambda item: item[1], reverse=True)[:top],
        "largest_files": [asdict(rec) for rec in largest],
        "old_files": [asdict(rec) for rec in old],
        "low_risk_pattern_matches": [asdict(rec) for rec in low_risk[:top]],
    }


def render_table(rows: Iterable[Iterable[str]]) -> list[str]:
    rows = [list(row) for row in rows]
    if not rows:
        return []
    header = rows[0]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows[1:]:
        safe = [cell.replace("\n", " ").replace("|", "\\|") for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return lines


def write_markdown(report: dict, path: Path) -> None:
    summary = report["summary"]
    lines: list[str] = []
    lines.append("# 清理电脑只读扫描报告")
    lines.append("")
    lines.append(f"- 生成时间: {report['generated_at']}")
    lines.append(f"- 主机: {platform.node()} / {platform.platform()}")
    lines.append(f"- 扫描范围: {', '.join(report['roots']) if report['roots'] else '未扫描用户目录'}")
    lines.append(f"- 文件数: {summary['total_files']}")
    lines.append(f"- 扫描到的总大小: {human_size(summary['total_size'])}")
    lines.append(f"- 只读模式: 是，本报告未修改任何文件")
    lines.append("")

    if report["drive_usage"]:
        lines.append("## 磁盘概况")
        drive_rows = [["磁盘", "总容量", "已用", "可用"]]
        for item in report["drive_usage"]:
            drive_rows.append([
                item["root"],
                human_size(item["total"]),
                human_size(item["used"]),
                human_size(item["free"]),
            ])
        lines.extend(render_table(drive_rows))
        lines.append("")

    lines.append("## 已知清理位置")
    known_rows = [["风险", "名称", "大小", "文件数", "路径", "建议", "迁移"]]
    for item in sorted(report["known_locations"], key=lambda x: x["size"] or 0, reverse=True):
        if not item["exists"] and item["size"] == 0:
            continue
        size_label = human_size(item["size"]) if item["measured"] else "未测量(高风险)"
        known_rows.append([
            item["risk"],
            item["name"],
            size_label,
            str(item["file_count"]) if item["measured"] else "-",
            item["path"],
            item["recommendation"],
            item.get("migration", ""),
        ])
    lines.extend(render_table(known_rows))
    lines.append("")

    lines.append("## 最大目录")
    dir_rows = [["大小", "目录"]]
    for directory, size in summary["top_directories"][:20]:
        dir_rows.append([human_size(size), directory])
    lines.extend(render_table(dir_rows))
    lines.append("")

    lines.append("## 最大文件")
    file_rows = [["大小", "修改时间", "路径"]]
    for rec in summary["largest_files"][:30]:
        file_rows.append([human_size(rec["size"]), rec["mtime"], rec["path"]])
    lines.extend(render_table(file_rows))
    lines.append("")

    lines.append("## 旧文件候选")
    old_rows = [["大小", "天数", "修改时间", "路径"]]
    for rec in summary["old_files"][:30]:
        old_rows.append([human_size(rec["size"]), str(rec["age_days"]), rec["mtime"], rec["path"]])
    lines.extend(render_table(old_rows))
    lines.append("")

    lines.append("## 扩展名占用")
    ext_rows = [["大小", "扩展名"]]
    for ext, size in summary["top_extensions"][:30]:
        ext_rows.append([human_size(size), ext])
    lines.extend(render_table(ext_rows))
    lines.append("")

    lines.append("## 低风险模式命中")
    low_rows = [["大小", "修改时间", "路径"]]
    for rec in summary["low_risk_pattern_matches"][:30]:
        low_rows.append([human_size(rec["size"]), rec["mtime"], rec["path"]])
    lines.extend(render_table(low_rows))
    lines.append("")

    duplicates = report["duplicates"]
    lines.append("## 重复文件候选")
    if duplicates["exact_hash_groups"]:
        dup_rows = [["可节省", "大小", "数量", "路径"]]
        for group in duplicates["exact_hash_groups"][:20]:
            dup_rows.append([
                human_size(group["potential_savings"]),
                human_size(group["size"]),
                str(group["count"]),
                "<br>".join(group["paths"][:8]),
            ])
        lines.extend(render_table(dup_rows))
    else:
        lines.append("- 未执行精确哈希，或未发现精确重复。可对候选路径再次运行 `--hash-duplicates`。")
        cand_rows = [["大小", "数量", "路径样例"]]
        for group in duplicates["same_size_candidate_groups"][:20]:
            cand_rows.append([human_size(group["size"]), str(group["count"]), "<br>".join(group["paths"][:5])])
        lines.extend(render_table(cand_rows))
    lines.append("")

    if report["errors"]:
        lines.append("## 扫描警告")
        for error in report["errors"][:100]:
            lines.append(f"- {error}")
        lines.append("")

    if report["skipped_dirs"]:
        lines.append("## 默认跳过目录")
        lines.append("- 下列目录被默认跳过以避免慢扫或误导；需要时可用 `--include-dev-heavy` 或 `--include-system` 重新扫描。")
        for skipped in report["skipped_dirs"][:100]:
            lines.append(f"- {skipped}")
        lines.append("")

    lines.append("## 下一步建议")
    lines.append("1. 先处理 low 风险且体积大的缓存/临时目录。")
    lines.append("2. 对 medium/high 风险项目逐项确认，必要时迁移或备份。")
    lines.append("3. 对重复文件只做候选审阅，不要自动删除。")
    lines.append("4. 执行后复扫，核对释放空间和失败项。")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only cleanup scanner")
    parser.add_argument("--root", action="append", default=[], help="Directory root to scan; repeatable")
    parser.add_argument("--include-common", action="store_true", help="Scan common user folders")
    parser.add_argument("--include-known", action="store_true", help="Measure known cache/system locations")
    parser.add_argument("--include-system", action="store_true", help="Do not skip system directory names during root scan")
    parser.add_argument("--include-dev-heavy", action="store_true", help="Scan node_modules and .git directories")
    parser.add_argument("--measure-high-risk-known", action="store_true", help="Measure high-risk known locations recursively")
    parser.add_argument("--hash-duplicates", action="store_true", help="Hash same-size files to confirm exact duplicates")
    parser.add_argument("--max-hash-mb", type=int, default=1024, help="Skip hashing files larger than this many MB")
    parser.add_argument("--max-files", type=int, default=200_000, help="Stop root scan after this many files")
    parser.add_argument("--old-days", type=int, default=365, help="Old file threshold in days")
    parser.add_argument("--top", type=int, default=50, help="Maximum rows per report section")
    parser.add_argument("--output", default=None, help="Output directory for reports")
    return parser.parse_args()


def default_output_dir() -> Path:
    cwd_output = Path.cwd() / "cleanup-reports"
    if not str(path_anchor(cwd_output)).lower().startswith("c:"):
        return cwd_output

    candidates: list[Path] = []
    for env_name in (
        "CLEANUP_REPORT_DIR",
        "SKILL_TMP_DIR",
        "WORKSPACE_TEMP",
        "PROJECT_TEMP",
        "TMPDIR",
        "TEMP",
        "TMP",
    ):
        raw = os.environ.get(env_name)
        if raw:
            candidates.append(Path(raw) / "cleanup-reports")
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        candidates.append(Path(codex_home) / ".tmp" / "cleanup-reports")
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:/")
        if drive.exists():
            candidates.append(drive / "cleanup-reports")

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not str(path_anchor(candidate)).lower().startswith("c:"):
            return candidate
    return cwd_output


def main() -> int:
    configure_stdio()
    args = parse_args()
    roots = [Path(item).expanduser() for item in args.root]
    if args.include_common or not roots:
        roots.extend(iter_common_roots())

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_roots: list[Path] = []
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            key = str(root)
        if key not in seen:
            seen.add(key)
            unique_roots.append(root)

    records, errors, skipped_dirs = scan_roots(
        unique_roots,
        include_system=args.include_system,
        include_dev_heavy=args.include_dev_heavy,
        max_files=args.max_files,
    )

    known_locations: list[KnownLocation] = []
    if args.include_known:
        known_locations, known_errors = scan_known_locations(measure_high_risk=args.measure_high_risk_known)
        errors.extend(known_errors)

    output_dir = Path(args.output).expanduser() if args.output else default_output_dir()
    if str(path_anchor(output_dir)).lower().startswith("c:"):
        errors.append(f"Output directory is on C: {output_dir}; prefer a non-C path for generated reports.")

    drive_paths = list(unique_roots) + [Path(item.path) for item in known_locations if item.exists] + [output_dir]
    report = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "roots": [str(path) for path in unique_roots],
        "drive_usage": [asdict(item) for item in collect_drive_usage(drive_paths)],
        "summary": summarize(records, top=args.top, old_days=args.old_days),
        "duplicates": find_duplicates(
            records,
            hash_files=args.hash_duplicates,
            max_hash_bytes=args.max_hash_mb * MB if args.max_hash_mb > 0 else None,
        ),
        "known_locations": [asdict(item) for item in known_locations],
        "skipped_dirs": skipped_dirs,
        "errors": errors,
    }

    out_dir = output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"cleanup_scan_{stamp}.json"
    md_path = out_dir / f"cleanup_scan_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, md_path)
    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote Markdown report: {md_path}")
    print(f"Scanned files: {report['summary']['total_files']}")
    print(f"Scanned size: {human_size(report['summary']['total_size'])}")
    if errors:
        print(f"Warnings: {len(errors)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
