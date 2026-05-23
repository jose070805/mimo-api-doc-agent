"""MiMo API Doc Agent - 基于 MiMo 模型的多 Agent 协作 API 文档自动生成系统"""

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
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 解析环境变量引用
    import os
    api_key = config.get("mimo", {}).get("api_key", "")
    if api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        config["mimo"]["api_key"] = os.environ.get(env_var, "")

    return config


def main():
    parser = argparse.ArgumentParser(
        description="MiMo API Doc Agent - 多 Agent 协作 API 文档自动生成"
    )
    parser.add_argument(
        "--repo", "-r",
        required=True,
        help="目标代码仓库路径"
    )
    parser.add_argument(
        "--output", "-o",
        default="./docs",
        help="文档输出目录 (默认: ./docs)"
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="配置文件路径 (默认: config.yaml)"
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="仅解析代码，不调用 MiMo 生成文档"
    )

    args = parser.parse_args()

    # 校验路径
    repo_path = Path(args.repo)
    if not repo_path.exists():
        console.print(f"[red]仓库路径不存在: {repo_path}[/red]")
        sys.exit(1)

    # 加载配置
    config = load_config(args.config)

    # 显示启动信息
    console.print(Panel(
        f"[bold]MiMo API Doc Agent[/bold]\n"
        f"仓库: {repo_path.resolve()}\n"
        f"输出: {Path(args.output).resolve()}\n"
        f"模式: {'仅解析' if args.parse_only else '完整流程'}",
        title="🚀 启动"
    ))

    # 执行
    orchestrator = Orchestrator(config)
    result = orchestrator.run(
        repo_path=str(repo_path),
        output_dir=args.output,
        parse_only=args.parse_only
    )

    return result


if __name__ == "__main__":
    main()
