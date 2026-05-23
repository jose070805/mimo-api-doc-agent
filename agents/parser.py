"""解析 Agent - 扫描代码仓库，提取接口和数据模型元信息"""

import re
from pathlib import Path
from typing import Optional
from rich.console import Console

console = Console()


class ParserAgent:
    """
    职责：扫描代码仓库，自动提取 API 路由定义、接口注释、数据模型变更。
    支持 Python (Flask/FastAPI/Django)、JavaScript/TypeScript (Express/NestJS)、Go (Gin)。
    """

    # ── 路由模式匹配 ──
    ROUTE_PATTERNS = {
        ".py": [
            # FastAPI: @app.get("/path"), @router.post("/path")
            r'@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            # Django: path("url", view)
            r'path\s*\(\s*["\']([^"\']+)["\']',
            # Flask: @app.route("/path", methods=["GET"])
            r'@\w+\.route\s*\(\s*["\']([^"\']+)["\'].*?methods\s*=\s*\[([^\]]+)\]',
        ],
        ".js": [
            # Express: app.get("/path", handler), router.post("/path")
            r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        ],
        ".ts": [
            # NestJS: @Get("/path"), @Post("/path")
            r'@(Get|Post|Put|Delete|Patch)\s*\(\s*["\']([^"\']*)["\']',
            # Express
            r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        ],
        ".go": [
            # Gin: r.GET("/path", handler)
            r'\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*"([^"]+)"',
        ],
    }

    # ── 数据模型模式 ──
    MODEL_PATTERNS = {
        ".py": [
            # Pydantic: class UserModel(BaseModel):
            r'class\s+(\w+)\s*\(\s*(?:Base|BaseModel|Schema)\w*\s*\)',
            # SQLAlchemy: class User(db.Model):
            r'class\s+(\w+)\s*\(\s*db\.Model\s*\)',
            # Dataclass
            r'@dataclass\s*\nclass\s+(\w+)',
        ],
        ".ts": [
            # Interface: interface UserDTO {
            r'interface\s+(\w+(?:DTO|Dto|Input|Output|Response|Request))\s*\{',
            # Type alias: type UserType = {
            r'type\s+(\w+)\s*=\s*\{',
        ],
        ".go": [
            # Struct: type User struct {
            r'type\s+(\w+)\s+struct\s*\{',
        ],
    }

    def __init__(self, config: dict):
        self.config = config
        parser_cfg = config.get("parser", {})
        self.extensions = set(parser_cfg.get("file_extensions", [".py", ".js", ".ts", ".go"]))
        self.ignore_dirs = set(parser_cfg.get("ignore_dirs", ["node_modules", "__pycache__", ".git"]))

    def run(self, repo_path: Path) -> dict:
        """
        扫描代码仓库，返回结构化的解析结果

        Returns:
            {
                "repo": str,
                "files": [{"path": str, "language": str, "content_preview": str}],
                "endpoints": [{"method": str, "path": str, "file": str, "line": int, "docstring": str}],
                "models": [{"name": str, "file": str, "line": int, "fields": str}]
            }
        """
        result = {
            "repo": str(repo_path),
            "files": [],
            "endpoints": [],
            "models": []
        }

        # 遍历文件
        for file_path in self._walk_files(repo_path):
            ext = file_path.suffix
            rel_path = file_path.relative_to(repo_path)

            # 读取文件内容
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            result["files"].append({
                "path": str(rel_path),
                "language": ext.lstrip("."),
                "content_preview": content[:500]
            })

            # 提取路由
            for ep in self._extract_endpoints(content, ext, str(rel_path)):
                result["endpoints"].append(ep)

            # 提取数据模型
            for model in self._extract_models(content, ext, str(rel_path)):
                result["models"].append(model)

        return result

    def _walk_files(self, repo: Path):
        """遍历仓库中的代码文件"""
        for path in repo.rglob("*"):
            if not path.is_file():
                continue
            # 跳过忽略目录
            if any(ignored in path.parts for ignored in self.ignore_dirs):
                continue
            if path.suffix in self.extensions:
                yield path

    def _extract_endpoints(self, content: str, ext: str, file_path: str) -> list:
        """从文件内容中提取 API 端点"""
        endpoints = []
        patterns = self.ROUTE_PATTERNS.get(ext, [])
        lines = content.split("\n")

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE):
                groups = match.groups()
                if len(groups) >= 2:
                    method = groups[0].upper()
                    path = groups[1]
                elif len(groups) == 1:
                    method = "GET"  # 默认
                    path = groups[0]
                else:
                    continue

                # 计算行号
                line_num = content[:match.start()].count("\n") + 1

                # 提取下方的 docstring / 注释
                docstring = self._extract_docstring(lines, line_num - 1)

                endpoints.append({
                    "method": method,
                    "path": path,
                    "file": file_path,
                    "line": line_num,
                    "docstring": docstring
                })

        return endpoints

    def _extract_models(self, content: str, ext: str, file_path: str) -> list:
        """从文件内容中提取数据模型"""
        models = []
        patterns = self.MODEL_PATTERNS.get(ext, [])
        lines = content.split("\n")

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                name = match.group(1)
                line_num = content[:match.start()].count("\n") + 1

                # 提取类体（简化：取后续 20 行）
                body_lines = lines[line_num - 1:line_num + 19]
                fields = "\n".join(body_lines)

                models.append({
                    "name": name,
                    "file": file_path,
                    "line": line_num,
                    "fields": fields
                })

        return models

    def _extract_docstring(self, lines: list, start_idx: int) -> str:
        """提取函数/路由下方的 docstring 或注释"""
        # 检查函数定义的下一行
        for i in range(start_idx + 1, min(start_idx + 5, len(lines))):
            line = lines[i].strip()
            if line.startswith('"""') or line.startswith("'''"):
                # 多行 docstring
                doc_lines = [line.lstrip('"\'')]
                for j in range(i + 1, min(i + 10, len(lines))):
                    doc_line = lines[j].strip()
                    doc_lines.append(doc_line)
                    if doc_line.endswith('"""') or doc_line.endswith("'''"):
                        break
                return " ".join(doc_lines).strip('"\' ')
            elif line.startswith("#"):
                # 单行注释
                return line.lstrip("# ").strip()
        return ""
