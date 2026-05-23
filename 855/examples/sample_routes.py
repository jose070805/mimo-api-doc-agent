"""
示例 Flask/FastAPI 路由文件
用于演示 Parser Agent 的解析能力
"""

from dataclasses import dataclass
from pydantic import BaseModel, Field
from typing import Optional, List


# ── 数据模型 ──

class UserCreate(BaseModel):
    """创建用户的请求体"""
    username: str = Field(..., min_length=3, max_length=32, description="用户名")
    email: str = Field(..., description="邮箱地址")
    password: str = Field(..., min_length=8, description="密码")
    avatar: Optional[str] = Field(None, description="头像 URL")


class UserResponse(BaseModel):
    """用户信息响应"""
    id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    email: str = Field(..., description="邮箱地址")
    avatar: Optional[str] = Field(None, description="头像 URL")
    created_at: str = Field(..., description="创建时间")


class ArticleCreate(BaseModel):
    """创建文章的请求体"""
    title: str = Field(..., max_length=200, description="文章标题")
    content: str = Field(..., description="文章内容（Markdown）")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    draft: bool = Field(False, description="是否为草稿")


class ArticleResponse(BaseModel):
    """文章信息响应"""
    id: int = Field(..., description="文章 ID")
    title: str = Field(..., description="文章标题")
    content: str = Field(..., description="文章内容")
    author: UserResponse = Field(..., description="作者信息")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    view_count: int = Field(0, description="浏览次数")
    created_at: str = Field(..., description="创建时间")
    updated_at: str = Field(..., description="更新时间")


# ── 路由定义（模拟 FastAPI 风格）──

# @app.get("/api/v1/users")
# 获取用户列表，支持分页和筛选
def list_users():
    """获取用户列表，支持分页和筛选"""
    pass


# @app.post("/api/v1/users")
# 创建新用户
def create_user():
    """创建新用户，需要用户名、邮箱和密码"""
    pass


# @app.get("/api/v1/users/{user_id}")
# 获取指定用户的详细信息
def get_user(user_id: int):
    """根据用户 ID 获取用户详情"""
    pass


# @app.put("/api/v1/users/{user_id}")
# 更新用户信息
def update_user(user_id: int):
    """更新用户信息，支持部分更新"""
    pass


# @app.delete("/api/v1/users/{user_id}")
# 删除用户
def delete_user(user_id: int):
    """删除指定用户（软删除）"""
    pass


# @app.get("/api/v1/articles")
# 获取文章列表
def list_articles():
    """获取文章列表，支持按标签和关键词筛选"""
    pass


# @app.post("/api/v1/articles")
# 创建新文章
def create_article():
    """创建新文章，支持草稿模式"""
    pass


# @app.get("/api/v1/articles/{article_id}")
# 获取文章详情
def get_article(article_id: int):
    """获取文章详情，同时增加浏览计数"""
    pass


# @app.put("/api/v1/articles/{article_id}")
# 更新文章
def update_article(article_id: int):
    """更新文章内容和标签"""
    pass


# @app.delete("/api/v1/articles/{article_id}")
# 删除文章
def delete_article(article_id: int):
    """删除文章，仅作者或管理员可操作"""
    pass


# @app.get("/api/v1/articles/{article_id}/comments")
# 获取文章评论
def list_comments(article_id: int):
    """获取指定文章的评论列表，支持分页"""
    pass


# @app.post("/api/v1/articles/{article_id}/comments")
# 发表评论
def create_comment(article_id: int):
    """在指定文章下发表评论"""
    pass
