"""生成 Agent - 调用 MiMo 生成规范化 API 文档（支持全量和增量模式）"""

import json
import os
from datetime import datetime, timezone
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

INCREMENTAL_PROMPT_TEMPLATE = """请更新以下 API 文档中变更的接口部分。

## 变更的接口
{changed_endpoints_json}

## 当前文档
{existing_doc}

请仅更新变更的接口，保持文档其余部分不变。返回完整的合并后文档。"""


class GeneratorAgent:
    """
    职责：将 Parser 输出的结构化元信息，通过 MiMo 长上下文能力转化为符合团队规范的 API 文档。
    支持多语言输出、全量生成和增量更新。
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

    def run(self, parse_result: dict,
            mode: str = "full",
            changed_endpoints: list[dict] | None = None,
            output_dir: str | None = None) -> dict:
        """
        为每种语言生成文档

        Args:
            parse_result: Parser Agent 的输出
            mode: "full" 全量生成 或 "incremental" 增量更新
            changed_endpoints: 增量模式下变更的接口列表
            output_dir: 文档输出目录（增量模式需要读取已有文档）

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
            console.print(f"  🌐 生成 {lang} 文档 (mode={mode})...")
            lang_name = "中文" if "zh" in lang else "English"

            if mode == "incremental" and output_dir:
                content = self._incremental_generate(
                    lang, lang_name, repo, changed_endpoints or [], output_dir
                )
                if content:
                    docs[lang] = content
                    continue
                console.print("    [dim]增量合并失败，回退到全量生成[/dim]")

            # 全量生成
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

    def _incremental_generate(
        self, lang: str, lang_name: str, repo: str,
        changed_endpoints: list[dict], output_dir: str,
    ) -> str | None:
        """增量更新：仅重新生成变更接口的文档并合并到已有文档"""
        doc_file = os.path.join(output_dir, f"api_doc_{lang}.md")
        if not os.path.exists(doc_file):
            return None

        with open(doc_file, "r", encoding="utf-8") as f:
            existing_doc = f.read()

        system = SYSTEM_PROMPT.format(language=lang_name)
        user = INCREMENTAL_PROMPT_TEMPLATE.format(
            changed_endpoints_json=json.dumps(changed_endpoints, ensure_ascii=False, indent=2),
            existing_doc=existing_doc[:8000],
        )

        try:
            content = self.client.chat(system, user)
            console.print(f"    [dim]增量更新完成，{len(content)} 字符[/dim]")
            return content
        except Exception as e:
            console.print(f"    [yellow]增量更新失败: {e}[/yellow]")
            return None

    def generate_with_template(
        self, parse_result: dict, template_path: str | None = None
    ) -> str:
        """使用 Jinja2 模板生成文档（备用方案，无需 MiMo 调用）"""
        from pathlib import Path

        if template_path is None:
            template_path = Path(__file__).parent.parent / "templates" / "api_doc.md.j2"

        with open(template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())

        repo_name = Path(parse_result.get("repo", "unknown")).name
        return template.render(
            repo_name=repo_name,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            endpoints=parse_result.get("endpoints", []),
            models=parse_result.get("models", []),
        )
