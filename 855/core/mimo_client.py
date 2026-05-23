"""MiMo API 客户端封装 — 支持重试、流式输出、Token 统计"""

import os
import json
import time
import re
from dataclasses import dataclass, field
from collections.abc import Generator
from typing import Optional

import requests
from rich.console import Console

console = Console()


@dataclass
class TokenUsage:
    """单次请求或累计的 Token 用量统计"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    request_count: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion
        self.request_count += 1

    def merge(self, other: "TokenUsage") -> "TokenUsage":
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.request_count += other.request_count
        return self

    def summary(self) -> str:
        return (
            f"requests={self.request_count} | "
            f"prompt={self.prompt_tokens:,} | "
            f"completion={self.completion_tokens:,} | "
            f"total={self.total_tokens:,}"
        )


class MiMoError(Exception):
    """MiMo API 通用错误"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class MiMoRateLimitError(MiMoError):
    """429 限流错误"""


class MiMoAuthError(MiMoError):
    """401/403 认证错误"""


class MiMoClient:
    """封装 MiMo API 调用，支持重试、流式输出、Token 统计"""

    def __init__(self, api_key: str, base_url: str, model: str,
                 max_tokens: int = 4096, temperature: float = 0.3,
                 max_retries: int = 3):
        self.api_key = api_key or os.environ.get("MIMO_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries
        self.usage = TokenUsage()

        if not self.api_key:
            raise ValueError("MIMO_API_KEY 未配置，请在 config.yaml 或环境变量中设置")

    def chat(self, system_prompt: str, user_prompt: str,
             temperature: Optional[float] = None,
             stream: bool = False) -> str | Generator[str, None, None]:
        """发送聊天请求，返回模型回复（或流式生成器）"""
        temp = temperature or self.temperature

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if stream:
            return self._chat_stream(messages, temp)
        return self._chat_sync(messages, temp)

    def _chat_sync(self, messages: list[dict], temperature: float) -> str:
        """同步请求，带指数退避重试"""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=120)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage_data = data.get("usage", {})
                self.usage.add(
                    usage_data.get("prompt_tokens", 0),
                    usage_data.get("completion_tokens", 0),
                )
                console.print(
                    f"  [dim]Token: {self.usage.summary()}[/dim]"
                )
                return content

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status == 429:
                    last_exc = MiMoRateLimitError(str(e), status_code=status)
                elif status in (401, 403):
                    raise MiMoAuthError(str(e), status_code=status)
                else:
                    last_exc = MiMoError(str(e), status_code=status)

            except requests.exceptions.RequestException as e:
                last_exc = e

            if attempt < self.max_retries - 1:
                wait = min(2 ** attempt, 30)
                console.print(f"  [yellow]请求失败，{wait}s 后重试 (attempt {attempt + 1}/{self.max_retries})[/yellow]")
                time.sleep(wait)

        if isinstance(last_exc, MiMoError):
            raise last_exc
        raise MiMoError(str(last_exc) if last_exc else "Unknown error")

    def _chat_stream(
        self, messages: list[dict], temperature: float
    ) -> Generator[str, None, None]:
        """流式请求，逐 chunk yield"""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, headers=headers, json=payload,
                                     timeout=300, stream=True)
                resp.raise_for_status()
                collected = 0
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta and delta["content"]:
                            collected += len(delta["content"])
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                # rough estimate of completion tokens
                self.usage.add(0, max(1, collected // 4))
                return
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status == 429:
                    last_exc = MiMoRateLimitError(str(e), status_code=status)
                elif status in (401, 403):
                    raise MiMoAuthError(str(e), status_code=status)
                else:
                    last_exc = MiMoError(str(e), status_code=status)
            except requests.exceptions.RequestException as e:
                last_exc = e

            if attempt < self.max_retries - 1:
                wait = min(2 ** attempt, 30)
                console.print(f"  [yellow]流式请求失败，{wait}s 后重试[/yellow]")
                time.sleep(wait)

        if isinstance(last_exc, MiMoError):
            raise last_exc
        raise MiMoError(str(last_exc) if last_exc else "Unknown error")

    def extract_json(self, text: str) -> dict:
        """从模型回复中提取 JSON"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

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
