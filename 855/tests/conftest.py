"""共享测试 fixtures"""

import json
import pytest
from pathlib import Path


@pytest.fixture
def sample_fastapi_file(tmp_path):
    """创建示例 FastAPI 文件"""
    content = '''
from fastapi import FastAPI

app = FastAPI()

@app.get("/users")
async def list_users(limit: int = 10, offset: int = 0):
    """获取用户列表，支持分页"""
    pass

@app.post("/users")
async def create_user(name: str, email: str):
    """创建新用户"""
    pass

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    """获取用户详情"""
    pass

@app.delete("/users/{user_id}")
async def delete_user(user_id: int):
    """删除用户"""
    pass
'''
    f = tmp_path / "api.py"
    f.write_text(content, encoding="utf-8")
    return str(f)


@pytest.fixture
def sample_express_file(tmp_path):
    """创建示例 Express TypeScript 文件"""
    content = '''
import express from 'express';
const app = express();

app.get('/api/users', (req, res) => res.json([]));
app.post('/api/users', (req, res) => res.status(201).json({}));
app.get('/api/users/:id', (req, res) => res.json({}));
'''
    f = tmp_path / "routes.ts"
    f.write_text(content, encoding="utf-8")
    return str(f)


@pytest.fixture
def sample_gin_file(tmp_path):
    """创建示例 Gin Go 文件"""
    content = '''
package main

import "github.com/gin-gonic/gin"

func main() {
    r := gin.Default()
    r.GET("/api/users", listUsers)
    r.POST("/api/users", createUser)
    r.GET("/api/users/:id", getUser)
}
func listUsers(c *gin.Context) {}
func createUser(c *gin.Context) {}
func getUser(c *gin.Context) {}
'''
    f = tmp_path / "main.go"
    f.write_text(content, encoding="utf-8")
    return str(f)


@pytest.fixture
def sample_parse_result():
    """模拟 Parser 解析结果"""
    return {
        "repo": "/mock/repo",
        "files": [
            {"path": "api.py", "language": "py", "content_preview": "from fastapi..."}
        ],
        "endpoints": [
            {"method": "GET", "path": "/users", "file": "api.py", "line": 5,
             "docstring": "获取用户列表，支持分页"},
            {"method": "POST", "path": "/users", "file": "api.py", "line": 11,
             "docstring": "创建新用户"},
            {"method": "GET", "path": "/users/{user_id}", "file": "api.py", "line": 17,
             "docstring": "获取用户详情"},
        ],
        "models": [
            {"name": "UserCreate", "file": "models.py", "line": 3,
             "fields": "username: str\nemail: str"},
        ]
    }


@pytest.fixture
def mock_config():
    """模拟配置"""
    return {
        "mimo": {
            "api_key": "test-key",
            "base_url": "https://api.test.com/v1",
            "model": "test-model",
            "max_tokens": 4096,
            "temperature": 0.3,
        },
        "parser": {
            "file_extensions": [".py", ".js", ".ts", ".go"],
            "ignore_dirs": ["node_modules", "__pycache__", ".git"],
        },
        "generator": {
            "languages": ["zh-CN"],
        },
        "validator": {
            "consistency_threshold": 0.85,
            "auto_fix_pr": True,
        }
    }
