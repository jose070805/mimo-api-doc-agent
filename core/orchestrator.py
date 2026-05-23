"""多 Agent 编排器"""

import json
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.panel import Panel

from agents.parser import ParserAgent
from agents.generator import GeneratorAgent
from agents.validator import ValidatorAgent

console = Console()


class Orchestrator:
    """编排三个 Agent 的执行流程"""

    def __init__(self, config: dict):
        self.config = config
        self.parser = ParserAgent(config)
        self.generator = GeneratorAgent(config)
        self.validator = ValidatorAgent(config)

    def run(self, repo_path: str, output_dir: str, parse_only: bool = False) -> dict:
        """
        执行完整的文档生成流程

        Args:
            repo_path: 目标代码仓库路径
            output_dir: 文档输出目录
            parse_only: 仅解析，不调用 MiMo

        Returns:
            执行结果摘要
        """
        repo = Path(repo_path).resolve()
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)

        result = {
            "repo": str(repo),
            "output": str(output),
            "timestamp": datetime.now().isoformat(),
            "stages": {}
        }

        # ── Stage 1: 解析 ──
        console.print(Panel("[bold blue]Stage 1/3: Parser Agent[/bold blue]", style="blue"))
        parse_result = self.parser.run(repo)
        result["stages"]["parse"] = {
            "files_scanned": len(parse_result.get("files", [])),
            "endpoints_found": len(parse_result.get("endpoints", [])),
            "models_found": len(parse_result.get("models", []))
        }
        console.print(f"  ✅ 扫描 {result['stages']['parse']['files_scanned']} 个文件, "
                      f"发现 {result['stages']['parse']['endpoints_found']} 个接口, "
                      f"{result['stages']['parse']['models_found']} 个数据模型")

        # 保存解析结果
        parse_output = output / "parse_result.json"
        with open(parse_output, "w", encoding="utf-8") as f:
            json.dump(parse_result, f, ensure_ascii=False, indent=2)

        if parse_only:
            console.print("[yellow]--parse-only 模式，跳过生成和校验[/yellow]")
            return result

        # ── Stage 2: 生成 ──
        console.print(Panel("[bold green]Stage 2/3: Generator Agent[/bold green]", style="green"))
        docs = self.generator.run(parse_result)
        result["stages"]["generate"] = {
            "docs_generated": len(docs),
            "languages": list(docs.keys())
        }

        for lang, content in docs.items():
            doc_file = output / f"api_doc_{lang}.md"
            with open(doc_file, "w", encoding="utf-8") as f:
                f.write(content)
            console.print(f"  📄 已生成: {doc_file.name} ({len(content)} 字符)")

        # ── Stage 3: 校验 ──
        console.print(Panel("[bold yellow]Stage 3/3: Validator Agent[/bold yellow]", style="yellow"))
        validation = self.validator.run(parse_result, docs)
        result["stages"]["validate"] = {
            "consistency_score": validation.get("consistency_score", 0),
            "issues_found": len(validation.get("issues", [])),
            "auto_fix_pr": validation.get("auto_fix_pr", False)
        }

        # 保存校验报告
        report_file = output / "validation_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(validation, f, ensure_ascii=False, indent=2)

        score = validation.get("consistency_score", 0)
        threshold = self.config.get("validator", {}).get("consistency_threshold", 0.85)
        if score >= threshold:
            console.print(f"  ✅ 一致性校验通过: {score:.0%}")
        else:
            console.print(f"  ⚠️  一致性校验未达标: {score:.0%} (阈值 {threshold:.0%})")
            for issue in validation.get("issues", []):
                console.print(f"     - {issue}")

        # 保存最终结果
        result_file = output / "run_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        console.print(Panel(
            f"[bold green]完成！[/bold green]\n"
            f"文档已输出到: {output}\n"
            f"Token 统计请查看上方各 Agent 日志",
            title="✨ 执行完毕"
        ))

        return result
