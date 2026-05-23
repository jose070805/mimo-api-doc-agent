"""MiMo API Doc Agent - 基于 MiMo 模型的多 Agent 协作 API 文档自动生成系统

Usage:
    python main.py --repo ./your-project                    # 全量生成
    python main.py --repo ./your-project --diff             # 仅处理变更文件
    python main.py --repo ./your-project --watch            # 监听文件变化
    python main.py --repo ./your-project --dry-run          # 预览，不调用 MiMo
    python main.py --repo ./your-project --validate-only    # 仅校验已有文档
"""

import argparse
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel

from core.orchestrator import Orchestrator

console = Console()


def load_config(config_path: str = None) -> dict:
    """加载配置文件"""
    default_path = Path(__file__).parent / "config.yaml"
    path = Path(config_path) if config_path else default_path

    if not path.exists():
        console.print(f"[red]配置文件不存在: {path}[/red]")
        console.print("[yellow]提示: 复制 config.yaml.example 为 config.yaml 并填入配置[/yellow]")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 解析环境变量引用 ${VAR_NAME}
    import os
    api_key = config.get("mimo", {}).get("api_key", "")
    if api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        config["mimo"]["api_key"] = os.environ.get(env_var, "")

    return config


def main():
    parser = argparse.ArgumentParser(
        description="MiMo API Doc Agent - 多 Agent 协作 API 文档自动生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --repo ./my-api                   全量生成 API 文档
  python main.py --repo . --diff                   仅处理 git diff 变更文件
  python main.py --repo . --watch                  监听文件变化自动重新生成
  python main.py --repo . --dry-run                预览模式（不调用 MiMo）
  python main.py --repo . --parse-only             仅解析，不调用 MiMo
  python main.py --repo . --auto-fix --pr          自动修复 + 生成 PR
        """,
    )
    parser.add_argument("--repo", "-r", required=True, help="目标代码仓库路径")
    parser.add_argument("--output", "-o", default="./docs", help="文档输出目录 (默认: ./docs)")
    parser.add_argument("--config", "-c", default=None, help="配置文件路径 (默认: config.yaml)")

    # 运行模式
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--diff", action="store_true",
                            help="仅处理 git diff 变更文件（增量模式）")
    mode_group.add_argument("--watch", action="store_true",
                            help="监听文件变化，自动重新生成文档")
    mode_group.add_argument("--dry-run", action="store_true",
                            help="预览模式：仅解析并显示检测到的接口，不调用 MiMo")
    mode_group.add_argument("--parse-only", action="store_true",
                            help="仅解析代码，不调用 MiMo 生成文档")
    mode_group.add_argument("--validate-only", metavar="DOC_PATH",
                            help="仅校验已有的文档文件")

    # 选项
    parser.add_argument("--auto-fix", action="store_true",
                        help="自动修复校验中发现的问题")
    parser.add_argument("--pr", action="store_true",
                        help="生成 PR 风格的修复提案")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        default="INFO", help="日志级别 (默认: INFO)")
    parser.add_argument("--log-format", choices=["console", "structured"],
                        default="console", help="日志格式 (默认: console)")

    args = parser.parse_args()

    # 校验路径
    repo_path = Path(args.repo)
    if not args.validate_only and not repo_path.exists():
        console.print(f"[red]仓库路径不存在: {repo_path}[/red]")
        sys.exit(1)

    # 加载配置
    config = load_config(args.config)

    # 配置日志
    _setup_logging(args)

    # --validate-only 模式
    if args.validate_only:
        return _run_validate_only(args.validate_only, config)

    # --diff 模式
    if args.diff:
        return _run_diff(repo_path, args, config)

    # --watch 模式
    if args.watch:
        return _run_watch(repo_path, args, config)

    # 常规运行
    orchestrator = Orchestrator(config)
    result = orchestrator.run(
        repo_path=str(repo_path),
        output_dir=args.output,
        parse_only=args.parse_only,
        mode="full",
        dry_run=args.dry_run,
        auto_fix=args.auto_fix,
        generate_pr=args.pr,
    )

    return result


def _setup_logging(args):
    """配置日志系统"""
    from utils.logger import setup_logging
    setup_logging(level=args.log_level, fmt=args.log_format)


def _run_validate_only(doc_path: str, config: dict):
    """独立校验模式"""
    from agents.validator import ValidatorAgent

    validator = ValidatorAgent(config)
    # Construct a minimal parse_result
    parse_result = {"endpoints": [], "models": [], "repo": "validate-only"}
    docs = {"zh-CN": Path(doc_path).read_text(encoding="utf-8")}
    result = validator.run(parse_result, docs, output_dir=str(Path(doc_path).parent))
    console.print(f"\n[bold]校验得分: {result['consistency_score']:.0%}[/bold]")
    console.print(f"发现问题: {len(result['issues'])} 个")
    return 0 if result["consistency_score"] >= config.get("validator", {}).get("consistency_threshold", 0.85) else 1


def _run_diff(repo_path: Path, args, config: dict):
    """增量模式：仅处理 git diff 变更文件"""
    from scanner.file_scanner import FileScanner
    from core.orchestrator import Orchestrator

    scanner = FileScanner(
        source_dirs=[str(repo_path)],
        extensions=config.get("parser", {}).get("file_extensions", [".py", ".js", ".ts", ".go"]),
        exclude_patterns=config.get("parser", {}).get("ignore_dirs", ["node_modules", "__pycache__", ".git"]),
    )

    changed = scanner.diff()
    if not changed:
        console.print("[yellow]没有检测到变更文件[/yellow]")
        return 0

    console.print(f"[green]检测到 {len(changed)} 个变更文件:[/green]")
    for f in changed:
        console.print(f"  - {f}")

    orchestrator = Orchestrator(config)
    result = orchestrator.run(
        repo_path=str(repo_path),
        output_dir=args.output,
        mode="incremental",
        changed_files=changed,
        dry_run=args.dry_run,
        auto_fix=args.auto_fix,
        generate_pr=args.pr,
    )
    return result


def _run_watch(repo_path: Path, args, config: dict):
    """监听模式：文件变化时自动重新生成"""
    from scanner.watcher import FileWatcher
    from core.orchestrator import Orchestrator

    extensions = config.get("parser", {}).get("file_extensions", [".py", ".js", ".ts", ".go"])
    extensions = [e if e.startswith(".") else f".{e}" for e in extensions]
    orchestrator = Orchestrator(config)

    def on_change(changed: list[str]):
        console.print(f"[yellow]检测到变更: {changed}[/yellow]")
        orchestrator.run(
            repo_path=str(repo_path),
            output_dir=args.output,
            mode="incremental",
            changed_files=changed,
            auto_fix=args.auto_fix,
            generate_pr=args.pr,
        )

    watcher = FileWatcher(
        paths=[str(repo_path)],
        extensions=extensions,
        callback=on_change,
        interval=2.0,
    )

    console.print(Panel(
        f"[bold]监听模式[/bold]\n"
        f"目录: {repo_path}\n"
        f"扩展名: {extensions}\n\n"
        f"按 Ctrl+C 停止",
        title="👀 Watch"
    ))

    watcher.run_forever()
    return 0


if __name__ == "__main__":
    main()
