from __future__ import annotations

import ast
import importlib.util
import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skills" / "qing-li-dian-nao"
SCRIPT = SKILL_DIR / "scripts" / "cleanup_scan.py"
TEST_ROOT = REPO / "qldn-test-root"
REPORT_ROOT = REPO / "qldn-test-reports"
README = REPO / "README.md"


def reset_dir(path: Path) -> None:
    if path.exists():
        resolved = path.resolve()
        if not str(resolved).lower().startswith(str(REPO.resolve()).lower()):
            raise RuntimeError(f"Refusing to remove outside repo: {resolved}")
        shutil.rmtree(resolved)
    path.mkdir(parents=True, exist_ok=True)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def cleanup() -> None:
    for path in (TEST_ROOT, REPORT_ROOT):
        if path.exists():
            resolved = path.resolve()
            if str(resolved).lower().startswith(str(REPO.resolve()).lower()):
                shutil.rmtree(resolved)


def load_module():
    spec = importlib.util.spec_from_file_location("cleanup_scan_under_test", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load cleanup_scan.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_scan(args: list[str], report_subdir: str) -> dict:
    out_dir = REPORT_ROOT / report_subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(SCRIPT), *args, "--output", str(out_dir)]
    result = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True, encoding="utf-8")
    if result.returncode != 0:
        raise AssertionError(f"scan failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    json_files = sorted(out_dir.glob("cleanup_scan_*.json"))
    md_files = sorted(out_dir.glob("cleanup_scan_*.md"))
    assert json_files, "JSON report was not written"
    assert md_files, "Markdown report was not written"
    data = json.loads(json_files[-1].read_text(encoding="utf-8"))
    md_text = md_files[-1].read_text(encoding="utf-8")
    for section in ["磁盘概况", "最大文件", "重复文件候选", "下一步建议"]:
        assert section in md_text, f"missing Markdown section: {section}"
    return data


def make_fixture() -> None:
    reset_dir(TEST_ROOT)
    reset_dir(REPORT_ROOT)
    write(TEST_ROOT / "docs" / "a.txt", "same duplicate payload\n")
    write(TEST_ROOT / "backup" / "b.txt", "same duplicate payload\n")
    write(TEST_ROOT / "same-size" / "x.bin", "abcd")
    write(TEST_ROOT / "same-size" / "y.bin", "wxyz")
    write(TEST_ROOT / "Temp" / "cache.tmp", "temporary cache")
    write(TEST_ROOT / "中文目录" / "数据.md", "# 标题\n")
    write(TEST_ROOT / "no_extension", "plain")
    old_path = TEST_ROOT / "old" / "archive.log"
    write(old_path, "old log")
    old_ts = time.time() - 400 * 24 * 60 * 60
    os.utime(old_path, (old_ts, old_ts))
    write(TEST_ROOT / "node_modules" / "pkg" / "ignored.js", "dependency")
    write(TEST_ROOT / ".git" / "objects" / "ignored", "git object")


def test_skill_files() -> None:
    required = [
        SKILL_DIR / "SKILL.md",
        SKILL_DIR / "agents" / "openai.yaml",
        SKILL_DIR / "references" / "research-synthesis.md",
        SCRIPT,
        REPO / "docs" / "integration.md",
    ]
    for path in required:
        assert path.exists(), f"missing required file: {path}"
        assert path.stat().st_size > 0, f"empty required file: {path}"

    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "name: qing-li-dian-nao" in skill
    assert "默认不删除、不移动、不改配置" in skill
    assert "--include-dev-heavy" in skill
    assert "--measure-high-risk-known" in skill
    assert "<skill-dir>" in skill
    assert "其他 AI 编程工具" in skill

    openai_yaml = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    assert "display_name: \"清理电脑\"" in openai_yaml
    assert "allow_implicit_invocation: true" in openai_yaml

    readme = README.read_text(encoding="utf-8")
    assert "AI 编程助手" in readme
    assert "docs/integration.md" in readme
    assert "面向 Codex 的安全电脑清理 skill" not in readme


def test_no_local_machine_paths() -> None:
    forbidden = [
        "E:" + "\\User" + "Data",
        "D:" + "\\桌面",
        "86" + "151",
    ]
    for path in SKILL_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".py", ".yaml", ".yml", ".txt"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in forbidden:
                assert marker not in text, f"local machine marker leaked in {path}: {marker}"


def test_static_no_destructive_or_network_calls() -> None:
    destructive_attrs = {"remove", "removedirs", "rmdir", "unlink", "rename"}
    destructive_pairs = {
        ("shutil", "rmtree"),
        ("shutil", "move"),
        ("shutil", "copytree"),
        ("os", "remove"),
        ("os", "removedirs"),
        ("os", "rmdir"),
        ("os", "system"),
        ("subprocess", "run"),
        ("subprocess", "Popen"),
    }
    forbidden_imports = {"requests", "urllib", "httpx", "openai"}
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_imports, f"network import found: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_imports, f"network import found: {node.module}"
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if isinstance(func.value, ast.Name):
                pair = (func.value.id, func.attr)
                assert pair not in destructive_pairs, f"destructive call found: {pair}"
            assert func.attr not in destructive_attrs, f"destructive method call found: {func.attr}"


def test_compile_and_help() -> None:
    py_compile.compile(str(SCRIPT), doraise=True)
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], text=True, capture_output=True, encoding="utf-8")
    assert result.returncode == 0
    for flag in ["--include-known", "--include-dev-heavy", "--measure-high-risk-known", "--hash-duplicates"]:
        assert flag in result.stdout


def test_scan_default_and_hash() -> None:
    data = run_scan([
        "--root",
        str(TEST_ROOT),
        "--hash-duplicates",
        "--old-days",
        "365",
        "--max-files",
        "100",
        "--top",
        "20",
    ], "default")
    assert data["summary"]["total_files"] == 8, data["summary"]["total_files"]
    assert data["duplicates"]["exact_hash_groups"], "expected exact duplicate group"
    assert data["duplicates"]["same_size_candidate_groups"], "expected same-size candidates"
    assert any("node_modules" in item for item in data["skipped_dirs"]), data["skipped_dirs"]
    assert any(".git" in item for item in data["skipped_dirs"]), data["skipped_dirs"]
    assert any("archive.log" in item["path"] for item in data["summary"]["old_files"])
    assert any("Temp" in item["path"] for item in data["summary"]["low_risk_pattern_matches"])
    assert data["drive_usage"], "expected drive usage data"


def test_scan_include_dev_heavy() -> None:
    data = run_scan([
        "--root",
        str(TEST_ROOT),
        "--include-dev-heavy",
        "--max-files",
        "100",
    ], "dev-heavy")
    assert data["summary"]["total_files"] == 10, data["summary"]["total_files"]
    assert not any("node_modules" in item for item in data["skipped_dirs"]), data["skipped_dirs"]
    assert not any(".git" in item for item in data["skipped_dirs"]), data["skipped_dirs"]


def test_limit_missing_root_and_known_location_switch() -> None:
    limited = run_scan(["--root", str(TEST_ROOT), "--max-files", "2"], "limited")
    assert limited["summary"]["total_files"] == 2
    assert any("Stopped at max file limit" in item for item in limited["errors"])

    missing = run_scan(["--root", str(TEST_ROOT / "does-not-exist"), "--max-files", "10"], "missing-root")
    assert missing["summary"]["total_files"] == 0
    assert any("Missing root" in item for item in missing["errors"])

    module = load_module()
    fake = TEST_ROOT / "known"
    write(fake / "high" / "blob.bin", "high-risk")
    write(fake / "low" / "cache.bin", "low-risk")
    module.known_paths = lambda: [
        ("Fake high", fake / "high", "high", "high risk fake", "", False),
        ("Fake low", fake / "low", "low", "low risk fake", "", True),
    ]
    default_items, _ = module.scan_known_locations(measure_high_risk=False)
    high = next(item for item in default_items if item.name == "Fake high")
    low = next(item for item in default_items if item.name == "Fake low")
    assert high.exists and high.size is None and not high.measured
    assert low.exists and low.size and low.measured

    measured_items, _ = module.scan_known_locations(measure_high_risk=True)
    high_measured = next(item for item in measured_items if item.name == "Fake high")
    assert high_measured.size and high_measured.measured


def test_default_output_dir_prefers_generic_non_c_env() -> None:
    module = load_module()
    original_env = os.environ.copy()
    original_cwd = Path.cwd()
    non_c_tmp = REPORT_ROOT / "non-c-temp"
    non_c_tmp.mkdir(parents=True, exist_ok=True)
    c_drive_cwd = Path.home()
    if not str(c_drive_cwd).lower().startswith("c:"):
        c_drive_cwd = Path("C:/")
    try:
        os.environ["CLEANUP_REPORT_DIR"] = str(non_c_tmp)
        os.environ.pop("CODEX_HOME", None)
        os.chdir(c_drive_cwd)
        output_dir = module.default_output_dir()
        assert str(output_dir).endswith("cleanup-reports")
        assert str(non_c_tmp / "cleanup-reports") == str(output_dir)
    finally:
        os.chdir(original_cwd)
        os.environ.clear()
        os.environ.update(original_env)


def main() -> int:
    cleanup()
    make_fixture()
    tests = [
        test_skill_files,
        test_no_local_machine_paths,
        test_static_no_destructive_or_network_calls,
        test_compile_and_help,
        test_scan_default_and_hash,
        test_scan_include_dev_heavy,
        test_limit_missing_root_and_known_location_switch,
        test_default_output_dir_prefers_generic_non_c_env,
    ]
    try:
        for test in tests:
            test()
            print(f"PASS {test.__name__}")
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
