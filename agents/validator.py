"""校验 Agent - 校验文档与代码的一致性"""

import json
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


class ValidatorAgent:
    """
    职责：对比 Parser 输出与 Generator 输出，检测文档与代码的不一致。
    支持自动生成修复 PR（可选）。
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

    def run(self, parse_result: dict, docs: dict) -> dict:
        """
        校验所有语言版本的文档

        Args:
            parse_result: Parser 的输出
            docs: Generator 的输出 {"lang": "content"}

        Returns:
            {
                "consistency_score": float,
                "issues": [...],
                "auto_fix_pr": bool,
                "details": {"lang": {...}}
            }
        """
        all_issues = []
        scores = []
        details = {}

        # 精简 parse_result 以减少 prompt 长度
        slim_parse = {
            "endpoints": [
                {"method": ep["method"], "path": ep["path"], "docstring": ep.get("docstring", "")}
                for ep in parse_result.get("endpoints", [])
            ],
            "models": [
                {"name": m["name"], "fields": m["fields"][:500]}
                for m in parse_result.get("models", [])
            ]
        }

        for lang, content in docs.items():
            console.print(f"  🔍 校验 {lang} 文档...")

            user = USER_PROMPT_TEMPLATE.format(
                parse_result=json.dumps(slim_parse, ensure_ascii=False, indent=2),
                language=lang,
                doc_content=content[:6000]  # 限制长度避免超 token
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

        return {
            "consistency_score": avg_score,
            "issues": all_issues,
            "auto_fix_pr": self.auto_fix and avg_score < self.threshold,
            "details": details
        }
