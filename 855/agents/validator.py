"""校验 Agent - 校验文档与代码的一致性，支持自动修复 PR 生成"""

import json
import os
from datetime import datetime, timezone
from typing import Optional
from rich.console import Console

from core.mimo_client import MiMoClient

console = Console()

SYSTEM_PROMPT = """你是一个 API 文档一致性校验专家。你的任务是对比代码解析结果与生成的文档，找出不一致的地方。

校验维度：
1. **接口完整性**：代码中定义的接口是否全部出现在文档中
2. **参数准确性**：文档中的请求参数是否与代码定义匹配
3. **路径正确性**：文档中的 URL 路径是否与代码路由一致
4. **模型完整性**：数据模型的字段是否在文档中完整列出
5. **描述准确性**：接口描述是否准确反映代码逻辑

输出要求：JSON 格式，包含 consistency_score（0-1）和 issues 列表。
"""

USER_PROMPT_TEMPLATE = """请对比以下代码解析结果与生成的文档，找出不一致的地方。

## 代码解析结果
{parse_result}

## 生成的文档（{language}）
{doc_content}

请输出校验结果，JSON 格式：
{{
  "consistency_score": 0.0-1.0,
  "issues": [
    {{
      "type": "missing_endpoint | wrong_param | wrong_path | missing_model_field | inaccurate_desc",
      "severity": "critical | warning | info",
      "location": "接口路径或模型名",
      "description": "具体问题描述",
      "suggestion": "修复建议"
    }}
  ],
  "summary": "整体评价"
}}
"""

AUTO_FIX_PROMPT = """请根据以下校验问题修复 API 文档。

## 校验问题
{issues_json}

## 当前文档
{current_doc}

请返回修复后的完整文档。只修改有问题的部分，保持其余内容不变。"""


class ValidatorAgent:
    """
    职责：对比 Parser 输出与 Generator 输出，检测文档与代码的不一致。
    支持自动生成修复 PR（auto_fix_pr）。
    """

    def __init__(self, config: dict):
        self.config = config
        mimo_cfg = config.get("mimo", {})
        self.client = MiMoClient(
            api_key=mimo_cfg.get("api_key", ""),
            base_url=mimo_cfg.get("base_url", "https://api.mimo.xiaomi.com/v1"),
            model=mimo_cfg.get("model", "mimo-v2.5-pro"),
            max_tokens=mimo_cfg.get("max_tokens", 4096),
            temperature=0.1  # 校验用更低温度
        )
        val_cfg = config.get("validator", {})
        self.threshold = val_cfg.get("consistency_threshold", 0.85)
        self.auto_fix = val_cfg.get("auto_fix_pr", True)

    def run(self, parse_result: dict, docs: dict,
            output_dir: str | None = None) -> dict:
        """
        校验所有语言版本的文档

        Args:
            parse_result: Parser 的输出
            docs: Generator 的输出 {"lang": "content"}
            output_dir: 文档输出目录（生成 PR 时需要）

        Returns:
            {
                "consistency_score": float,
                "issues": [...],
                "auto_fix_pr": bool,
                "details": {"lang": {...}},
                "pr_path": str or None
            }
        """
        all_issues = []
        scores = []
        details = {}

        slim_parse = {
            "endpoints": [
                {"method": ep["method"], "path": ep["path"],
                 "docstring": ep.get("docstring", ""),
                 "file": ep.get("file", "")}
                for ep in parse_result.get("endpoints", [])
            ],
            "models": [
                {"name": m["name"], "fields": m["fields"][:500],
                 "file": m.get("file", "")}
                for m in parse_result.get("models", [])
            ]
        }

        for lang, content in docs.items():
            console.print(f"  🔍 校验 {lang} 文档...")

            user = USER_PROMPT_TEMPLATE.format(
                parse_result=json.dumps(slim_parse, ensure_ascii=False, indent=2),
                language=lang,
                doc_content=content[:6000]
            )

            try:
                resp = self.client.chat(SYSTEM_PROMPT, user, temperature=0.1)
                result = self.client.extract_json(resp)

                score = result.get("consistency_score", 0)
                issues = result.get("issues", [])

                scores.append(score)
                all_issues.extend(issues)
                details[lang] = result

                console.print(f"    得分: {score:.0%}, 问题: {len(issues)} 个")

            except Exception as e:
                console.print(f"    [red]校验 {lang} 失败: {e}[/red]")
                scores.append(0)
                details[lang] = {"error": str(e)}

        avg_score = sum(scores) / len(scores) if scores else 0
        needs_fix = self.auto_fix and avg_score < self.threshold

        result = {
            "consistency_score": avg_score,
            "issues": all_issues,
            "auto_fix_pr": needs_fix,
            "details": details,
            "pr_path": None,
        }

        # 自动修复 PR 生成
        if needs_fix and output_dir:
            pr_path = self._generate_pr(docs, all_issues, avg_score, output_dir)
            result["pr_path"] = pr_path

            # 同时尝试自动修复文档
            for lang, content in docs.items():
                fixed = self._auto_fix_doc(content, all_issues, lang, output_dir)
                if fixed:
                    result[f"fixed_{lang}"] = fixed

        return result

    def _auto_fix_doc(
        self, doc_content: str, issues: list[dict],
        lang: str, output_dir: str,
    ) -> str | None:
        """使用 MiMo 自动修复文档中的问题"""
        # 只处理 critical 和 warning 级别的问题
        serious_issues = [i for i in issues if i.get("severity") in ("critical", "warning")]
        if not serious_issues:
            return None

        console.print(f"  🔧 尝试自动修复 {lang} 文档 ({len(serious_issues)} 个问题)...")

        user = AUTO_FIX_PROMPT.format(
            issues_json=json.dumps(serious_issues, ensure_ascii=False, indent=2),
            current_doc=doc_content[:8000],
        )

        try:
            fixed = self.client.chat(SYSTEM_PROMPT, user, temperature=0.2)
            fixed_path = os.path.join(
                output_dir, f"api_doc_{lang}_fixed.md"
            )
            with open(fixed_path, "w", encoding="utf-8") as f:
                f.write(fixed)
            console.print(f"    [green]✅ 修复文档已保存: {fixed_path}[/green]")
            return fixed_path
        except Exception as e:
            console.print(f"    [red]自动修复失败: {e}[/red]")
            return None

    def _generate_pr(
        self, docs: dict, issues: list[dict],
        score: float, output_dir: str,
    ) -> str:
        """生成 PR 风格的 Markdown 修复提案"""
        pr_dir = os.path.join(output_dir, "pr-proposals")
        os.makedirs(pr_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        pr_file = os.path.join(pr_dir, f"doc-fixes-{timestamp}.md")

        lines = [
            f"# API 文档修复提案 — {timestamp}",
            "",
            f"**一致性评分:** {score:.0%}",
            f"**问题总数:** {len(issues)}",
            f"**涉及语言:** {', '.join(docs.keys())}",
            "",
            "## 问题清单",
            "",
        ]

        severity_icons = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
        for i, issue in enumerate(issues, 1):
            icon = severity_icons.get(issue.get("severity", "info"), "⚪")
            lines.append(f"### {icon} #{i} [{issue.get('severity', 'info').upper()}] {issue.get('type', '')}")
            lines.append(f"- **位置:** {issue.get('location', 'N/A')}")
            lines.append(f"- **问题:** {issue.get('description', 'N/A')}")
            lines.append(f"- **建议:** {issue.get('suggestion', 'N/A')}")
            lines.append("")

        lines.append("## 修复检查清单")
        lines.append("")
        for i, issue in enumerate(issues, 1):
            lines.append(f"- [ ] #{i} {issue.get('location', '')}: {issue.get('description', '')[:80]}")

        lines.append("")
        lines.append("---")
        lines.append(f"*此 PR 由 MiMo API Doc Agent Validator 自动生成*")

        content = "\n".join(lines)
        with open(pr_file, "w", encoding="utf-8") as f:
            f.write(content)

        console.print(f"  📋 [bold]修复 PR 已生成:[/bold] {pr_file}")
        return pr_file
