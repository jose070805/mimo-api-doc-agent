"""MiMo API 客户端封装"""

import os
import json
import requests
from typing import Optional
from rich.console import Console

console = Console()


class MiMoClient:
    """封装 MiMo API 调用"""

    def __init__(self, api_key: str, base_url: str, model: str,
                 max_tokens: int = 4096, temperature: float = 0.3):
        self.api_key = api_key or os.environ.get("MIMO_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

        if not self.api_key:
            raise ValueError("MIMO_API_KEY 未配置，请在 config.yaml 或环境变量中设置")

    def chat(self, system_prompt: str, user_prompt: str,
             temperature: Optional[float] = None) -> str:
        """发送聊天请求，返回模型回复"""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": self.max_tokens,
            "temperature": temperature or self.temperature
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {})
            console.print(f"  [dim]Token 消耗: prompt={tokens_used.get('prompt_tokens', '?')}, "
                          f"completion={tokens_used.get('completion_tokens', '?')}[/dim]")
            return content
        except requests.exceptions.RequestException as e:
            console.print(f"  [red]API 调用失败: {e}[/red]")
            raise

    def extract_json(self, text: str) -> dict:
        """从模型回复中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown code block 中提取
        import re
        patterns = [
            r"```json\s*\n(.*?)\n```",
            r"```\s*\n(.*?)\n```",
            r"\{.*\}",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1) if match.lastindex else match.group())
                except (json.JSONDecodeError, IndexError):
                    continue

        raise ValueError(f"无法从回复中提取 JSON:\n{text[:500]}")
