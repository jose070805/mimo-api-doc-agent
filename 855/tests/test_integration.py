"""端到端集成测试"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import Orchestrator


class TestFullPipeline:
    """测试完整的三阶段流水线"""

    @patch("core.orchestrator.ParserAgent")
    @patch("core.orchestrator.GeneratorAgent")
    @patch("core.orchestrator.ValidatorAgent")
    def test_full_pipeline_success(self, mock_validator, mock_generator, mock_parser,
                                    mock_config, tmp_path):
        """完整流水线应成功执行"""
        # Mock Parser
        mock_parser_instance = Mock()
        mock_parser_instance.run.return_value = {
            "repo": "/test",
            "files": [{"path": "api.py", "language": "py", "content_preview": "..."}],
            "endpoints": [
                {"method": "GET", "path": "/users", "file": "api.py",
                 "line": 5, "docstring": "List users"}
            ],
            "models": []
        }
        mock_parser.return_value = mock_parser_instance

        # Mock Generator
        mock_generator_instance = Mock()
        mock_generator_instance.run.return_value = {"zh-CN": "# API Docs\n\nGET /users"}
        mock_generator.return_value = mock_generator_instance

        # Mock Validator
        mock_validator_instance = Mock()
        mock_validator_instance.run.return_value = {
            "consistency_score": 0.9,
            "issues": [],
            "auto_fix_pr": False,
            "details": {"zh-CN": {"consistency_score": 0.9}},
            "pr_path": None
        }
        mock_validator.return_value = mock_validator_instance

        orchestrator = Orchestrator(mock_config)
        output_dir = tmp_path / "docs"

        result = orchestrator.run(
            repo_path=str(tmp_path),
            output_dir=str(output_dir),
        )

        assert "stages" in result
        assert result["stages"]["parse"]["endpoints_found"] == 1
        assert result["stages"]["generate"]["docs_generated"] == 1
        assert result["stages"]["validate"]["consistency_score"] == 0.9

        # 应生成输出文件
        assert (output_dir / "parse_result.json").exists()
        assert (output_dir / "api_doc_zh-CN.md").exists()
        assert (output_dir / "validation_report.json").exists()
        assert (output_dir / "run_result.json").exists()

    @patch("core.orchestrator.ParserAgent")
    def test_parse_only_mode(self, mock_parser, mock_config, tmp_path):
        """--parse-only 模式只执行解析"""
        mock_parser_instance = Mock()
        mock_parser_instance.run.return_value = {
            "repo": "/test",
            "files": [],
            "endpoints": [],
            "models": []
        }
        mock_parser.return_value = mock_parser_instance

        orchestrator = Orchestrator(mock_config)
        output_dir = tmp_path / "docs"

        result = orchestrator.run(
            repo_path=str(tmp_path),
            output_dir=str(output_dir),
            parse_only=True,
        )

        assert result["stages"]["parse"]["endpoints_found"] == 0
        assert "generate" not in result["stages"]
        assert "validate" not in result["stages"]

    @patch("core.orchestrator.ParserAgent")
    @patch("core.orchestrator.GeneratorAgent")
    @patch("core.orchestrator.ValidatorAgent")
    def test_incremental_mode(self, mock_validator, mock_generator, mock_parser,
                               mock_config, tmp_path):
        """增量模式仅处理变更文件"""
        mock_parser_instance = Mock()
        mock_parser_instance.run.return_value = {
            "repo": "/test",
            "files": [
                {"path": "api.py", "language": "py", "content_preview": "..."},
                {"path": "new.py", "language": "py", "content_preview": "..."},
            ],
            "endpoints": [
                {"method": "GET", "path": "/users", "file": "api.py", "line": 5, "docstring": ""},
                {"method": "POST", "path": "/items", "file": "new.py", "line": 3, "docstring": ""},
            ],
            "models": []
        }
        mock_parser.return_value = mock_parser_instance

        mock_generator_instance = Mock()
        mock_generator_instance.run.return_value = {"zh-CN": "# Updated Docs"}
        mock_generator.return_value = mock_generator_instance

        mock_validator_instance = Mock()
        mock_validator_instance.run.return_value = {
            "consistency_score": 0.88,
            "issues": [],
            "auto_fix_pr": False,
            "details": {},
            "pr_path": None
        }
        mock_validator.return_value = mock_validator_instance

        orchestrator = Orchestrator(mock_config)
        output_dir = tmp_path / "docs"

        result = orchestrator.run(
            repo_path=str(tmp_path),
            output_dir=str(output_dir),
            mode="incremental",
            changed_files=["new.py"],
        )

        assert result["mode"] == "incremental"
        assert result["stages"]["parse"]["endpoints_found"] == 2

    @patch("core.orchestrator.ParserAgent")
    def test_dry_run_mode(self, mock_parser, mock_config, tmp_path):
        """dry-run 模式不写入文件"""
        mock_parser_instance = Mock()
        mock_parser_instance.run.return_value = {
            "repo": "/test",
            "files": [{"path": "api.py", "language": "py", "content_preview": "..."}],
            "endpoints": [
                {"method": "GET", "path": "/users", "file": "api.py",
                 "line": 5, "docstring": "Get users"},
                {"method": "POST", "path": "/users", "file": "api.py",
                 "line": 10, "docstring": "Create user"},
            ],
            "models": [{"name": "User", "file": "models.py", "line": 1, "fields": "..."}]
        }
        mock_parser.return_value = mock_parser_instance

        orchestrator = Orchestrator(mock_config)
        output_dir = tmp_path / "docs"

        result = orchestrator.run(
            repo_path=str(tmp_path),
            output_dir=str(output_dir),
            dry_run=True,
        )

        # 不应生成文件（dry-run 跳过生成和校验）
        assert "generate" not in result["stages"]
        assert "validate" not in result["stages"]
        assert not (output_dir / "api_doc_zh-CN.md").exists()

    @patch("core.orchestrator.ParserAgent")
    @patch("core.orchestrator.GeneratorAgent")
    @patch("core.orchestrator.ValidatorAgent")
    def test_auto_fix_and_pr(self, mock_validator, mock_generator, mock_parser,
                              mock_config, tmp_path):
        """验证自动修复和 PR 生成流程"""
        mock_parser_instance = Mock()
        mock_parser_instance.run.return_value = {
            "repo": "/test", "files": [], "endpoints": [], "models": []
        }
        mock_parser.return_value = mock_parser_instance

        mock_generator_instance = Mock()
        mock_generator_instance.run.return_value = {"zh-CN": "# Docs"}
        mock_generator.return_value = mock_generator_instance

        mock_validator_instance = Mock()
        mock_validator_instance.run.return_value = {
            "consistency_score": 0.7,
            "issues": [{"type": "missing_endpoint", "severity": "critical"}],
            "auto_fix_pr": True,
            "details": {},
            "pr_path": str(tmp_path / "docs" / "pr-proposals" / "fix.md")
        }
        mock_validator.return_value = mock_validator_instance

        orchestrator = Orchestrator(mock_config)
        output_dir = tmp_path / "docs"

        result = orchestrator.run(
            repo_path=str(tmp_path),
            output_dir=str(output_dir),
            auto_fix=True,
            generate_pr=True,
        )

        assert result["stages"]["validate"]["consistency_score"] == 0.7
        assert result["stages"]["validate"]["auto_fix_pr"] is True
