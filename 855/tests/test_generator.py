"""GeneratorAgent 单元测试"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.generator import GeneratorAgent


class TestGeneratorInit:
    """测试 GeneratorAgent 初始化"""

    def test_default_languages(self, mock_config):
        agent = GeneratorAgent(mock_config)
        assert "zh-CN" in agent.languages

    def test_multiple_languages(self, mock_config):
        config = mock_config.copy()
        config["generator"] = {"languages": ["zh-CN", "en"]}
        agent = GeneratorAgent(config)
        assert agent.languages == ["zh-CN", "en"]


class TestGeneratorRun:
    """测试 run() 方法"""

    @patch("agents.generator.MiMoClient")
    def test_empty_result(self, mock_client_class, mock_config):
        """空解析结果应优雅处理"""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        agent = GeneratorAgent(mock_config)
        result = agent.run({"endpoints": [], "models": [], "repo": "test"})

        assert result == {}

    @patch("agents.generator.MiMoClient")
    def test_generates_doc_calls_mimo(self, mock_client_class, mock_config, sample_parse_result):
        """应调用 MiMo 生成文档"""
        mock_client = Mock()
        mock_client.chat.return_value = "# API Docs\n\nContent here"
        mock_client_class.return_value = mock_client

        # 抑制 console 输出
        mock_console = Mock()
        with patch("agents.generator.console", mock_console):
            agent = GeneratorAgent(mock_config)
            result = agent.run(sample_parse_result)

        assert "zh-CN" in result
        assert "# API Docs" in result["zh-CN"]
        assert mock_client.chat.called

    @patch("agents.generator.MiMoClient")
    def test_api_error_generates_placeholder(self, mock_client_class, mock_config, sample_parse_result):
        """MiMo 调用失败时应生成占位内容"""
        mock_client = Mock()
        mock_client.chat.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        mock_console = Mock()
        with patch("agents.generator.console", mock_console):
            agent = GeneratorAgent(mock_config)
            result = agent.run(sample_parse_result)

        assert "zh-CN" in result
        assert "生成失败" in result["zh-CN"]

    @patch("agents.generator.MiMoClient")
    def test_incremental_mode(self, mock_client_class, mock_config, sample_parse_result, tmp_path):
        """增量模式应读取已有文档并合并"""
        # 创建已有文档
        output_dir = tmp_path / "docs"
        output_dir.mkdir()
        existing_doc = output_dir / "api_doc_zh-CN.md"
        existing_doc.write_text("# Old API Docs\n\nOld content", encoding="utf-8")

        mock_client = Mock()
        mock_client.chat.return_value = "# Merged API Docs\n\nUpdated content"
        mock_client_class.return_value = mock_client

        mock_console = Mock()
        with patch("agents.generator.console", mock_console):
            agent = GeneratorAgent(mock_config)
            result = agent.run(
                sample_parse_result,
                mode="incremental",
                changed_endpoints=[sample_parse_result["endpoints"][0]],
                output_dir=str(output_dir),
            )

        assert "zh-CN" in result
        assert "# Merged" in result["zh-CN"]


class TestGeneratorTemplate:
    """测试模板渲染"""

    @patch("agents.generator.MiMoClient")
    def test_generate_with_template(self, mock_client_class, mock_config, sample_parse_result):
        """Jinja2 模板渲染应正常工作"""
        agent = GeneratorAgent(mock_config)
        output = agent.generate_with_template(sample_parse_result)

        assert "api.py" in output or "mock" in output
        assert "GET" in output
        assert "/users" in output
