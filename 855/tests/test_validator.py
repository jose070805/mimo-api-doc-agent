"""ValidatorAgent 单元测试"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.validator import ValidatorAgent


class TestValidatorInit:
    """测试 ValidatorAgent 初始化"""

    def test_default_threshold(self, mock_config):
        agent = ValidatorAgent(mock_config)
        assert agent.threshold == 0.85
        assert agent.auto_fix is True

    def test_custom_threshold(self, mock_config):
        config = mock_config.copy()
        config["validator"] = {"consistency_threshold": 0.9, "auto_fix_pr": False}
        agent = ValidatorAgent(config)
        assert agent.threshold == 0.9
        assert agent.auto_fix is False


class TestValidatorRun:
    """测试 run() 方法"""

    @patch("agents.validator.MiMoClient")
    def test_validation_high_score(self, mock_client_class, mock_config, sample_parse_result):
        """高分校验结果"""
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "consistency_score": 0.95,
            "issues": [],
            "summary": "All good"
        })
        mock_client.extract_json.return_value = {
            "consistency_score": 0.95,
            "issues": [],
            "summary": "All good"
        }
        mock_client_class.return_value = mock_client

        docs = {"zh-CN": "# API Docs\n\nGET /users - list users"}
        mock_console = Mock()
        with patch("agents.validator.console", mock_console):
            agent = ValidatorAgent(mock_config)
            result = agent.run(sample_parse_result, docs)

        assert result["consistency_score"] == 0.95
        assert result["issues"] == []
        assert result["auto_fix_pr"] is False

    @patch("agents.validator.MiMoClient")
    def test_validation_low_score_triggers_fix(self, mock_client_class, mock_config, sample_parse_result, tmp_path):
        """低分应触发自动修复"""
        mock_client = Mock()
        # 第一次调用：校验
        mock_client.chat.side_effect = [
            json.dumps({
                "consistency_score": 0.6,
                "issues": [{"type": "missing_endpoint", "severity": "critical",
                           "location": "GET /users", "description": "Missing",
                           "suggestion": "Add it"}],
                "summary": "Needs fix"
            }),
            # 第二次调用：自动修复
            "# Fixed API Docs\n\nFixed content",
        ]
        mock_client.extract_json.return_value = {
            "consistency_score": 0.6,
            "issues": [{"type": "missing_endpoint", "severity": "critical",
                       "location": "GET /users", "description": "Missing",
                       "suggestion": "Add it"}],
            "summary": "Needs fix"
        }
        mock_client_class.return_value = mock_client

        output_dir = tmp_path / "docs"
        output_dir.mkdir()

        docs = {"zh-CN": "# API Docs\n\nIncomplete"}
        mock_console = Mock()
        with patch("agents.validator.console", mock_console):
            agent = ValidatorAgent(mock_config)
            result = agent.run(sample_parse_result, docs, output_dir=str(output_dir))

        assert result["consistency_score"] == 0.6
        assert result["auto_fix_pr"] is True
        assert result["pr_path"] is not None
        # 应生成修复后的文档
        fixed_key = "fixed_zh-CN"
        assert fixed_key in result

    @patch("agents.validator.MiMoClient")
    def test_api_error_graceful_degradation(self, mock_client_class, mock_config, sample_parse_result):
        """API 错误应优雅降级"""
        mock_client = Mock()
        mock_client.chat.side_effect = Exception("Network Error")
        mock_client_class.return_value = mock_client

        docs = {"zh-CN": "# Docs"}
        mock_console = Mock()
        with patch("agents.validator.console", mock_console):
            agent = ValidatorAgent(mock_config)
            result = agent.run(sample_parse_result, docs)

        assert result["consistency_score"] == 0
        assert "error" in result["details"]["zh-CN"]


class TestPRGeneration:
    """PR 生成测试"""

    @patch("agents.validator.MiMoClient")
    def test_generates_pr_file(self, mock_client_class, mock_config, sample_parse_result, tmp_path):
        """应生成 PR 修复提案文件"""
        mock_client = Mock()
        mock_client.chat.return_value = json.dumps({
            "consistency_score": 0.5,
            "issues": [
                {"type": "wrong_param", "severity": "warning",
                 "location": "POST /users", "description": "参数不匹配",
                 "suggestion": "检查 email 字段"}
            ],
            "summary": "Issues found"
        })
        mock_client.extract_json.return_value = {
            "consistency_score": 0.5,
            "issues": [
                {"type": "wrong_param", "severity": "warning",
                 "location": "POST /users", "description": "参数不匹配",
                 "suggestion": "检查 email 字段"}
            ],
            "summary": "Issues found"
        }
        mock_client_class.return_value = mock_client

        output_dir = tmp_path / "docs"
        output_dir.mkdir()

        docs = {"zh-CN": "# Docs"}
        mock_console = Mock()
        with patch("agents.validator.console", mock_console):
            agent = ValidatorAgent(mock_config)
            result = agent.run(sample_parse_result, docs, output_dir=str(output_dir))

        assert result["pr_path"] is not None
        assert Path(result["pr_path"]).exists()
        pr_content = Path(result["pr_path"]).read_text(encoding="utf-8")
        assert "参数不匹配" in pr_content
        assert "wrong_param" in pr_content
