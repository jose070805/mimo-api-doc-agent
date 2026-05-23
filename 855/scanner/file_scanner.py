"""文件扫描器 — 发现源文件 & git diff 变更检测"""

import os
import subprocess
from pathlib import Path


class FileScanner:
    """扫描源文件并检测 git 变更"""

    def __init__(self, source_dirs: list[str], extensions: list[str],
                 exclude_patterns: list[str] | None = None):
        self.source_dirs = [Path(d) for d in source_dirs]
        self.extensions = [e if e.startswith(".") else f".{e}" for e in extensions]
        self.exclude_patterns = exclude_patterns or []

    def scan(self) -> list[str]:
        """递归查找所有匹配的源文件"""
        files: list[str] = []
        for src in self.source_dirs:
            if not src.exists():
                continue
            for root, dirs, filenames in os.walk(src):
                dirs[:] = [d for d in dirs
                           if not any(p in d for p in self.exclude_patterns)]
                for fname in filenames:
                    if Path(fname).suffix.lower() in self.extensions:
                        files.append(os.path.join(root, fname))
        return sorted(files)

    def diff(self, base_ref: str = "HEAD~1") -> list[str]:
        """获取自某 git ref 以来变更的文件"""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", base_ref],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
            return [f for f in result.stdout.strip().split("\n")
                    if f and self._matches(f)]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def diff_staged(self) -> list[str]:
        """获取已暂存的文件（适合 pre-commit hook）"""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return []
            return [f for f in result.stdout.strip().split("\n")
                    if f and self._matches(f)]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def _matches(self, filepath: str) -> bool:
        ext = Path(filepath).suffix.lower()
        if ext not in self.extensions:
            return False
        return not any(p in filepath for p in self.exclude_patterns)
