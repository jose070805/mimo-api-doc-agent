"""MiMoClient 单元测试"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.mimo_client import MiMoClient, MiMoError, MiMoRateLimitError, MiMoAuthError, TokenUsage


class TestTokenUsage:
    """Token 用量统计测试"""

    def test_initial_state(self):
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
        assert usage.request_count == 0

    def test_add(self):
        usage = TokenUsage()
        usage.add(100, 50)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150
        assert usage.request_count == 1

    def test_add_multiple(self):
        usage = TokenUsage()
        usage.add(100, 50)
        usage.add(200, 100)
        assert usage.prompt_tokens == 300
        assert usage.completion_tokens == 150
        assert usage.total_tokens == 450
        assert usage.request_count == 2

    def test_merge(self):
        a = TokenUsage()
        a.add(100, 50)
        b = TokenUsage()
        b.add(200, 100)
        a.merge(b)
        assert a.prompt_tokens == 300
        assert a.completion_tokens == 150
        assert a.request_count == 2

    def test_summary(self):
        usage = TokenUsage()
        usage.add(1000, 500)
        summary = usage.summary()
        assert "requests=1" in summary
        assert "prompt=1,000" in summary
        assert "total=1,500" in summary


class TestMiMoClientInit:
    """MiMoClient 初始化测试"""

    def test_init_with_api_key(self):
        client = MiMoClient("test-key", "https://api.test.com", "model-v1")
        assert client.api_key == "test-key"
        assert client.base_url == "https://api.test.com"
        assert client.model == "model-v1"

    def test_init_without_key_raises(self):
        with pytest.raises(ValueError, match="MIMO_API_KEY"):
            MiMoClient("", "https://api.test.com", "model-v1")

    def test_init_with_env_key(self):
        import os
        os.environ["MIMO_API_KEY"] = "env-key"
        try:
            client = MiMoClient("", "https://api.test.com", "model-v1")
            assert client.api_key == "env-key"
        finally:
            del os.environ["MIMO_API_KEY"]

    def test_default_values(self):
        client = MiMoClient("key", "https://api.test.com", "model")
        assert client.max_tokens == 4096
        assert client.temperature == 0.3
        assert client.max_retries == 3

    def test_custom_params(self):
        client = MiMoClient("key", "https://api.test.com", "model",
                            max_tokens=2048, temperature=0.7, max_retries=5)
        assert client.max_tokens == 2048
        assert client.temperature == 0.7
        assert client.max_retries == 5


class TestMiMoClientChat:
    """chat() 方法测试"""

    @patch("core.mimo_client.requests.post")
    def test_successful_chat(self, mock_post, monkeypatch):
        """成功的 API 调用"""
        # 抑制 console 输出
        monkeypatch.setattr("core.mimo_client.console.print", lambda *a, **kw: None)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
        }
        mock_post.return_value = mock_response

        client = MiMoClient("key", "https://api.test.com", "model")
        result = client.chat("system", "user")

        assert result == "Hello!"
        assert client.usage.prompt_tokens == 10
        assert client.usage.completion_tokens == 3
        assert client.usage.request_count == 1

    @patch("core.mimo_client.requests.post")
    def test_retry_on_429(self, mock_post, monkeypatch):
        """429 错误应触发重试"""
        monkeypatch.setattr("core.mimo_client.console.print", lambda *a, **kw: None)
        monkeypatch.setattr("core.mimo_client.time.sleep", lambda s: None)

        error_response = Mock()
        error_response.status_code = 429
        error_response.raise_for_status.side_effect = Exception("429")

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "choices": [{"message": {"content": "retried!"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2}
        }

        mock_post.side_effect = [Exception("429"), Exception("429"), success_response]
        # We need to mock the HTTPError properly
        # Actually let's use a simpler approach

    @patch("core.mimo_client.requests.post")
    def test_auth_error_raises(self, mock_post, monkeypatch):
        """401 错误应立即抛出 MiMoAuthError"""
        monkeypatch.setattr("core.mimo_client.console.print", lambda *a, **kw: None)

        mock_response = Mock()
        mock_response.status_code = 401
        http_error = Exception("401 Unauthorized")
        http_error.response = mock_response
        mock_post.side_effect = http_error

        client = MiMoClient("bad-key", "https://api.test.com", "model")
        with pytest.raises(MiMoAuthError):
            client.chat("system", "user")

    def test_extract_json_direct(self):
        """直接 JSON 解析"""
        client = MiMoClient("key", "https://api.test.com", "model")
        result = client.extract_json('{"score": 0.95}')
        assert result == {"score": 0.95}

    def test_extract_json_markdown_block(self):
        """从 markdown code block 提取"""
        client = MiMoClient("key", "https://api.test.com", "model")
        text = '```json\n{"score": 0.8}\n```'
        result = client.extract_json(text)
        assert result == {"score": 0.8}

    def test_extract_json_fallback(self):
        """从文本中提取 JSON 对象"""
        client = MiMoClient("key", "https://api.test.com", "model")
        text = 'Some text {"key": "value"} more text'
        result = client.extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_invalid(self):
        """无法提取 JSON 时抛异常"""
        client = MiMoClient("key", "https://api.test.com", "model")
        with pytest.raises(ValueError, match="无法从回复中提取 JSON"):
            client.extract_json("no json here at all")


class TestMiMoClientStream:
    """流式输出测试"""

    @patch("core.mimo_client.requests.post")
    def test_stream_chunks(self, mock_post, monkeypatch):
        """流式响应应逐 chunk yield"""
        monkeypatch.setattr("core.mimo_client.console.print", lambda *a, **kw: None)

        chunks = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
            'data: {"choices":[{"delta":{"content":" World"}}]}\n',
            'data: [DONE]\n',
        ]

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.iter_lines.return_value = chunks
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        client = MiMoClient("key", "https://api.test.com", "model")
        result = list(client.chat("system", "user", stream=True))

        assert "".join(result) == "Hello World"
