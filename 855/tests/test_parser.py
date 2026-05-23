"""ParserAgent 单元测试"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

# 确保项目根在 sys.path 中
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.parser import ParserAgent


class TestParserAgentInit:
    """测试 ParserAgent 初始化"""

    def test_default_config(self, mock_config):
        agent = ParserAgent(mock_config)
        assert ".py" in agent.extensions
        assert ".js" in agent.extensions
        assert ".go" in agent.extensions
        assert "__pycache__" in agent.ignore_dirs

    def test_custom_extensions(self):
        config = {"parser": {"file_extensions": [".py"], "ignore_dirs": ["test"]}}
        agent = ParserAgent(config)
        assert agent.extensions == {".py"}
        assert "test" in agent.ignore_dirs


class TestParserAgentRun:
    """测试 run() 方法"""

    def test_scan_fastapi_file(self, mock_config, sample_fastapi_file):
        agent = ParserAgent(mock_config)
        result = agent.run(Path(sample_fastapi_file).parent)

        # 应该至少找到 4 个 FastAPI 路由
        endpoints = result["endpoints"]
        methods = [ep["method"] for ep in endpoints]
        assert "GET" in methods
        assert "POST" in methods or any(ep["path"] == "/users" and ep["method"] == "POST" for ep in endpoints)
        assert len(endpoints) >= 4

    def test_scan_express_file(self, mock_config, sample_express_file):
        agent = ParserAgent(mock_config)
        result = agent.run(Path(sample_express_file).parent)

        endpoints = result["endpoints"]
        assert len(endpoints) >= 2
        paths = [ep["path"] for ep in endpoints]
        assert any("/api/users" in p for p in paths)

    def test_scan_gin_file(self, mock_config, sample_gin_file):
        agent = ParserAgent(mock_config)
        result = agent.run(Path(sample_gin_file).parent)

        endpoints = result["endpoints"]
        assert len(endpoints) >= 2
        assert any(ep["method"] == "GET" for ep in endpoints)

    def test_empty_repo(self, mock_config, tmp_path):
        agent = ParserAgent(mock_config)
        result = agent.run(tmp_path)

        assert result["endpoints"] == []
        assert result["models"] == []
        assert result["files"] == []

    def test_ignore_dirs(self, mock_config, sample_fastapi_file):
        config = mock_config.copy()
        config["parser"]["ignore_dirs"].append("api.py")  # 不是目录名，但测试排除模式
        agent = ParserAgent(config)
        result = agent.run(Path(sample_fastapi_file).parent)
        # api.py 不在 ignore_dirs 中（它是文件名），所以应该仍会扫描
        assert len(result["files"]) >= 1

    def test_return_structure(self, mock_config, sample_fastapi_file):
        agent = ParserAgent(mock_config)
        result = agent.run(Path(sample_fastapi_file).parent)

        assert "repo" in result
        assert "files" in result
        assert "endpoints" in result
        assert "models" in result
        for ep in result["endpoints"]:
            assert "method" in ep
            assert "path" in ep
            assert "file" in ep
            assert "line" in ep
            assert "docstring" in ep


class TestASTParsing:
    """测试 Python AST 解析"""

    def test_fastapi_ast_routes(self, mock_config, sample_fastapi_file):
        """AST 应该能精确解析 FastAPI 路由"""
        agent = ParserAgent(mock_config)
        result = agent.run(Path(sample_fastapi_file).parent)

        endpoints = {(ep["method"], ep["path"]) for ep in result["endpoints"]}
        assert ("GET", "/users") in endpoints
        assert ("POST", "/users") in endpoints
        assert ("GET", "/users/{user_id}") in endpoints
        assert ("DELETE", "/users/{user_id}") in endpoints

    def test_ast_model_detection(self, mock_config, tmp_path):
        """应该检测 Pydantic/SQLAlchemy 数据模型"""
        content = """
from pydantic import BaseModel

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
"""
        f = tmp_path / "models.py"
        f.write_text(content, encoding="utf-8")
        agent = ParserAgent(mock_config)
        result = agent.run(tmp_path)

        model_names = [m["name"] for m in result["models"]]
        assert "UserCreate" in model_names
        assert "UserResponse" in model_names

    def test_ast_params_extraction(self, mock_config, tmp_path):
        """AST 解析应提取函数参数"""
        content = '''
from fastapi import FastAPI

app = FastAPI()

@app.get("/search")
async def search(q: str, page: int = 1, limit: int = 20):
    """Search endpoint"""
    pass
'''
        f = tmp_path / "search.py"
        f.write_text(content, encoding="utf-8")
        agent = ParserAgent(mock_config)
        result = agent.run(tmp_path)

        search_ep = [ep for ep in result["endpoints"] if ep["path"] == "/search"]
        assert len(search_ep) == 1
        ep = search_ep[0]
        if "params" in ep:
            param_names = [p["name"] for p in ep["params"]]
            assert "q" in param_names


class TestRegexFallback:
    """测试 regex 备用解析"""

    def test_django_urlpatterns(self, mock_config, tmp_path):
        """测试 Django urlpatterns 正则匹配"""
        content = """
from django.urls import path
from . import views

urlpatterns = [
    path("api/users/", views.list_users),
    path("api/users/<int:pk>/", views.user_detail),
]
"""
        f = tmp_path / "urls.py"
        f.write_text(content, encoding="utf-8")
        agent = ParserAgent(mock_config)
        result = agent.run(tmp_path)

        paths = [ep["path"] for ep in result["endpoints"]]
        assert any("api/users" in p for p in paths)

    def test_syntax_error_file(self, mock_config, tmp_path):
        """语法错误的 Python 文件应优雅降级到 regex"""
        content = "this is not valid python @@@"
        f = tmp_path / "broken.py"
        f.write_text(content, encoding="utf-8")
        agent = ParserAgent(mock_config)
        # 不应抛出异常
        result = agent.run(tmp_path)
        assert "endpoints" in result
