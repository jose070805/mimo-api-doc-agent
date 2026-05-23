"""生成 Agent - 调用 MiMo 生成规范化 API 文档"""

import json
from typing import Optional
from jinja2 import Template
from rich.console import Console

from core.mimo_client import MiMoClient

console = Console()

SYSTEM_PROMPT = """你是一个专业的 API 文档生成专家。你的任务是根据提供的代码解析结果，生成结构清晰、内容准确的 API 文档。

要求：
1. 文档必须包含：接口概述、请求方法、URL 路径、请求参数、响应格式、错误码
2. 每个接口附带 curl 调用示例
3. 数据模型需要列出所有字段及其类型、说明
4. 使用清晰的 Markdown 格式
5. 语言：{language}
6. 风格：专业但易读，适合团队内部开发者阅读
"""

USER_PROMPT_TEMPLATE = """请根据以下代码解析结果，生成完整的 API 文档。

## 仓库信息
仓库路径: {repo}

## 发现的 API 接口 ({endpoint_count} 个)
{endpoints_json}

## 发现的数据模型 ({model_count} 个)
{models_json}

请生成完整的 Markdown 格式 API 文档。"""


class GeneratorAgent:
    """
    职责：将 Parser 输出的结构化元信息，通过 MiMo 长上下文能力转化为符合团队规范的 API 文档。
    支持多语言输出。
    """

    def __init__(self, config: dict):
        self.config = config
        mimo_cfg = config.get("mimo", {})
        self.client = MiMoClient(
            api_key=mimo_cfg.get("api_key", ""),
            base_url=mimo_cfg.get("base_url", "https://api.mimo.xiaomi.com/v1"),
            model=mimo_cfg.get("model", "mimo-v2.5-pro"),
            max_tokens=mimo_cfg.get("max_tokens", 4096),
            temperature=mimo_cfg.get("temperature", 0.3)
        )
        gen_cfg = config.get("generator", {})
        self.languages = gen_cfg.get("languages", ["zh-CN"])

    def run(self, parse_result: dict) -> dict:
        """
        为每种语言生成文档

        Args:
            parse_result: Parser Agent 的输出

        Returns:
            {"zh-CN": "...", "en": "..."}
        """
        docs = {}

        endpoints = parse_result.get("endpoints", [])
        models = parse_result.get("models", [])
        repo = parse_result.get("repo", "unknown")

        if not endpoints and not models:
            console.print("  [yellow]⚠️  未发现任何接口或模型，跳过生成[/yellow]")
            return docs

        for lang in self.languages:
            console.print(f"  🌐 生成 {lang} 文档...")
            lang_name = "中文" if "zh" in lang else "English"

            system = SYSTEM_PROMPT.format(language=lang_name)
            user = USER_PROMPT_TEMPLATE.format(
                repo=repo,
                endpoint_count=len(endpoints),
                endpoints_json=json.dumps(endpoints, ensure_ascii=False, indent=2),
                model_count=len(models),
                models_json=json.dumps(models, ensure_ascii=False, indent=2)
            )

            try:
                content = self.client.chat(system, user)
                docs[lang] = content
                console.print(f"    [dim]生成完成，{len(content)} 字符[/dim]")
            except Exception as e:
                console.print(f"    [red]生成 {lang} 文档失败: {e}[/red]")
                docs[lang] = f"<!-- 生成失败: {e} -->"

        return docs
