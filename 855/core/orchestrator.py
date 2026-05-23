"""多 Agent 编排器 — 支持全量、增量、dry-run 模式"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime

from agents.parser import ParserAgent
from agents.generator import GeneratorAgent
from agents.validator import ValidatorAgent
from utils.stats import StatsTracker

logger = logging.getLogger("mimodoc.orchestrator")


class Orchestrator:
    """编排三个 Agent 的执行流程"""

    def __init__(self, config: dict):
        self.config = config
        self.parser = ParserAgent(config)
        self.generator = GeneratorAgent(config)
        self.validator = ValidatorAgent(config)
        self.stats = StatsTracker()

    def run(self, repo_path: str, output_dir: str,
            parse_only: bool = False,
            mode: str = "full",
            changed_files: list[str] | None = None,
            dry_run: bool = False,
            auto_fix: bool = False,
            generate_pr: bool = False) -> dict:
        """
        执行完整的文档生成流程

        Args:
            repo_path: 目标代码仓库路径
            output_dir: 文档输出目录
            parse_only: 仅解析，不调用 MiMo
            mode: "full" | "incremental"
            changed_files: 增量模式下的变更文件列表
            dry_run: 预览模式 — 不写文件、不调用 MiMo
            auto_fix: 自动修复校验问题
            generate_pr: 生成修复 PR

        Returns:
            执行结果摘要
        """
        start_time = time.monotonic()
        repo = Path(repo_path).resolve()
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)

        result = {
            "repo": str(repo),
            "output": str(output),
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "stages": {}
        }

        # ── Stage 1: 解析 ──
        t0 = time.monotonic()
        logger.info("Stage 1/3: Parser Agent (mode=%s)", mode)

        parse_result = self.parser.run(repo)
        result["stages"]["parse"] = {
            "files_scanned": len(parse_result.get("files", [])),
            "endpoints_found": len(parse_result.get("endpoints", [])),
            "models_found": len(parse_result.get("models", []))
        }
        self.stats.record_phase("parse", time.monotonic() - t0)
        logger.info("解析完成: %d 文件, %d 接口, %d 模型",
                     result["stages"]["parse"]["files_scanned"],
                     result["stages"]["parse"]["endpoints_found"],
                     result["stages"]["parse"]["models_found"])

        if dry_run:
            self._print_dry_run(parse_result, output)
            return result

        # 保存解析结果
        parse_output = output / "parse_result.json"
        with open(parse_output, "w", encoding="utf-8") as f:
            json.dump(parse_result, f, ensure_ascii=False, indent=2)

        if parse_only:
            logger.info("--parse-only 模式，跳过生成和校验")
            return result

        # ── Stage 2: 生成 ──
        t1 = time.monotonic()
        logger.info("Stage 2/3: Generator Agent")

        kwargs = {}
        if mode == "incremental":
            kwargs["mode"] = "incremental"
            kwargs["output_dir"] = str(output)
            # 提取变更的端点
            if changed_files:
                changed_endpoints = [
                    ep for ep in parse_result.get("endpoints", [])
                    if ep.get("file") in changed_files
                ]
                kwargs["changed_endpoints"] = changed_endpoints

        docs = self.generator.run(parse_result, **kwargs)
        result["stages"]["generate"] = {
            "docs_generated": len(docs),
            "languages": list(docs.keys())
        }
        self.stats.record_phase("generate", time.monotonic() - t1)

        for lang, content in docs.items():
            doc_file = output / f"api_doc_{lang}.md"
            with open(doc_file, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("已生成: %s (%d 字符)", doc_file.name, len(content))

        # ── Stage 3: 校验 ──
        t2 = time.monotonic()
        logger.info("Stage 3/3: Validator Agent")

        validation = self.validator.run(parse_result, docs, output_dir=str(output))
        result["stages"]["validate"] = {
            "consistency_score": validation.get("consistency_score", 0),
            "issues_found": len(validation.get("issues", [])),
            "auto_fix_pr": validation.get("auto_fix_pr", False)
        }
        self.stats.record_phase("validate", time.monotonic() - t2)

        # 保存校验报告
        report_file = output / "validation_report.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(validation, f, ensure_ascii=False, indent=2)

        score = validation.get("consistency_score", 0)
        threshold = self.config.get("validator", {}).get("consistency_threshold", 0.85)
        if score >= threshold:
            logger.info("一致性校验通过: %.0f%%", score * 100)
        else:
            logger.warning("一致性校验未达标: %.0f%% (阈值 %.0f%%)", score * 100, threshold * 100)
            for issue in validation.get("issues", [])[:5]:
                logger.warning("  - %s", issue.get("description", str(issue)))

        # 保存最终结果
        result_file = output / "run_result.json"
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        total_time = time.monotonic() - start_time
        logger.info("流水线完成 (%.1fs)", total_time)
        logger.info(self.stats.report())

        return result

    def _print_dry_run(self, parse_result: dict, output: Path):
        """预览模式输出"""
        endpoints = parse_result.get("endpoints", [])
        models = parse_result.get("models", [])

        print("\n=== DRY RUN: 检测到的 API 接口 ===\n")
        if not endpoints:
            print("  未检测到任何 API 接口")
        else:
            by_file: dict[str, list] = {}
            for ep in endpoints:
                f = ep.get("file", "unknown")
                by_file.setdefault(f, []).append(ep)

            for fname, eps in sorted(by_file.items()):
                print(f"  [{fname}]")
                for ep in eps:
                    method = ep.get("method", "?")
                    path = ep.get("path", "?")
                    doc = ep.get("docstring", "")[:70]
                    print(f"    {method:7s} {path:35s}  {doc}")
                print()

        print(f"  接口: {len(endpoints)} 个")
        print(f"  模型: {len(models)} 个")
        print(f"  输出目录: {output} (不会写入文件)\n")
