"""解析 Agent - 扫描代码仓库，提取接口和数据模型元信息

支持 AST 解析（Python）和正则表达式回退（所有语言）。
"""

import ast
import re
from pathlib import Path
from typing import Optional
from rich.console import Console

console = Console()


class ParserAgent:
    """
    职责：扫描代码仓库，自动提取 API 路由定义、接口注释、数据模型变更。
    Python 文件使用 AST 解析获得更高准确度，其他语言使用正则表达式。
    支持 Python (Flask/FastAPI/Django)、JavaScript/TypeScript (Express/NestJS)、Go (Gin)。
    """

    # ── 路由模式匹配（regex 回退 & 非 Python 语言）──
    ROUTE_PATTERNS = {
        ".py": [
            r'@(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            r'path\s*\(\s*["\']([^"\']+)["\']',
            r'@\w+\.route\s*\(\s*["\']([^"\']+)["\'].*?methods\s*=\s*\[([^\]]+)\]',
        ],
        ".js": [
            r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        ],
        ".ts": [
            r'@(Get|Post|Put|Delete|Patch)\s*\(\s*["\']([^"\']*)["\']',
            r'(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
        ],
        ".go": [
            r'\.(GET|POST|PUT|DELETE|PATCH)\s*\(\s*"([^"]+)"',
        ],
    }

    # ── 数据模型模式 ──
    MODEL_PATTERNS = {
        ".py": [
            r'class\s+(\w+)\s*\(\s*(?:Base|BaseModel|Schema)\w*\s*\)',
            r'class\s+(\w+)\s*\(\s*db\.Model\s*\)',
            r'@dataclass\s*\nclass\s+(\w+)',
        ],
        ".ts": [
            r'interface\s+(\w+(?:DTO|Dto|Input|Output|Response|Request))\s*\{',
            r'type\s+(\w+)\s*=\s*\{',
        ],
        ".go": [
            r'type\s+(\w+)\s+struct\s*\{',
        ],
    }

    # FastAPI HTTP 方法名映射
    FASTAPI_METHODS = {"get": "GET", "post": "POST", "put": "PUT",
                       "delete": "DELETE", "patch": "PATCH", "head": "HEAD", "options": "OPTIONS"}

    def __init__(self, config: dict):
        self.config = config
        parser_cfg = config.get("parser", {})
        self.extensions = set(parser_cfg.get("file_extensions", [".py", ".js", ".ts", ".go"]))
        self.ignore_dirs = set(parser_cfg.get("ignore_dirs", ["node_modules", "__pycache__", ".git"]))

    def run(self, repo_path: Path) -> dict:
        """
        扫描代码仓库，返回结构化的解析结果
        """
        result = {
            "repo": str(repo_path),
            "files": [],
            "endpoints": [],
            "models": []
        }

        for file_path in self._walk_files(repo_path):
            ext = file_path.suffix
            rel_path = file_path.relative_to(repo_path)

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            result["files"].append({
                "path": str(rel_path),
                "language": ext.lstrip("."),
                "content_preview": content[:500]
            })

            # Python 文件优先使用 AST 解析
            if ext == ".py":
                endpoints, models = self._parse_python_ast(content, str(rel_path))
                if endpoints or models:
                    result["endpoints"].extend(endpoints)
                    result["models"].extend(models)
                    continue

            # 回退到 regex（非 Python 或 AST 解析失败）
            for ep in self._extract_endpoints(content, ext, str(rel_path)):
                result["endpoints"].append(ep)
            for model in self._extract_models(content, ext, str(rel_path)):
                result["models"].append(model)

        return result

    # ── AST 解析（Python）───────────────────────────────────

    def _parse_python_ast(self, content: str, file_path: str) -> tuple[list, list]:
        """使用 Python ast 模块精确解析路由和模型"""
        endpoints: list[dict] = []
        models: list[dict] = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return [], []

        for node in ast.walk(tree):
            # 数据模型: class Foo(BaseModel) / class Foo(db.Model)
            if isinstance(node, ast.ClassDef):
                model = self._extract_ast_model(node, file_path, content)
                if model:
                    models.append(model)
                    continue

            # 路由: @app.get("/path") / @router.post("/path")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    ep = self._extract_ast_route(deco, node, file_path, content)
                    if ep:
                        endpoints.append(ep)

        # 同时尝试 regex 补充 Django urlpatterns
        for ep in self._extract_endpoints_regex(content, ".py", file_path):
            if not any(e["method"] == ep["method"] and e["path"] == ep["path"]
                       for e in endpoints):
                endpoints.append(ep)

        return endpoints, models

    def _extract_ast_route(self, decorator: ast.expr, func: ast.FunctionDef | ast.AsyncFunctionDef,
                           file_path: str, source: str) -> dict | None:
        """从 AST 装饰器节点提取 FastAPI/Flask 路由"""
        if not isinstance(decorator, ast.Call):
            return None

        # FastAPI: @app.get("/path") or @router.post("/path")
        if isinstance(decorator.func, ast.Attribute):
            attr = decorator.func.attr
            method = self.FASTAPI_METHODS.get(attr)
            if method and decorator.args:
                arg = decorator.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    path = arg.value
                    docstring = ast.get_docstring(func) or ""
                    params = self._extract_ast_params(func)
                    return {
                        "method": method,
                        "path": path,
                        "file": file_path,
                        "line": func.lineno,
                        "docstring": docstring,
                        "params": params,
                    }

        # Flask: @app.route("/path", methods=["GET", "POST"])
        if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "route":
            if decorator.args:
                arg = decorator.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    path = arg.value
                    methods = ["GET"]
                    for kw in decorator.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, ast.List):
                            methods = [
                                e.value.upper() if isinstance(e, ast.Constant) else "GET"
                                for e in kw.value.elts
                            ]
                    docstring = ast.get_docstring(func) or ""
                    # Return first method as primary, others could be additional entries
                    return {
                        "method": methods[0],
                        "path": path,
                        "file": file_path,
                        "line": func.lineno,
                        "docstring": docstring,
                        "params": [],
                    }

        return None

    def _extract_ast_model(self, node: ast.ClassDef, file_path: str, source: str) -> dict | None:
        """从 AST 类节点提取 Pydantic / SQLAlchemy 数据模型"""
        model_types = ("BaseModel", "Base", "Schema", "db.Model")
        for base in node.bases:
            base_name = self._get_base_name(base)
            if base_name and any(t in base_name for t in model_types):
                lines = source.split("\n")
                start = node.lineno - 1
                end = min(start + 30, len(lines))
                fields = "\n".join(lines[start:end])
                return {
                    "name": node.name,
                    "file": file_path,
                    "line": node.lineno,
                    "fields": fields,
                }
        return None

    @staticmethod
    def _get_base_name(base: ast.expr) -> str | None:
        if isinstance(base, ast.Name):
            return base.id
        if isinstance(base, ast.Attribute):
            return base.attr
        return None

    def _extract_ast_params(self, func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict]:
        """从函数签名中提取参数名和类型注解"""
        params = []
        for arg in func.args.args:
            param = {"name": arg.arg, "type": "any"}
            if arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    param["type"] = arg.annotation.id
                elif isinstance(arg.annotation, ast.Constant) and arg.annotation.value is None:
                    param["type"] = "None"
                elif isinstance(arg.annotation, ast.Subscript):
                    param["type"] = self._unparse_annotation(arg.annotation)
            params.append(param)
        return params

    @staticmethod
    def _unparse_annotation(node: ast.expr) -> str:
        """将注解 AST 节点转为字符串（Python 3.8 兼容）"""
        try:
            return ast.unparse(node)
        except AttributeError:
            import astor
            return astor.to_source(node).strip()
        except Exception:
            return "unknown"

    # ── Regex 回退 ──

    def _extract_endpoints(self, content: str, ext: str, file_path: str) -> list:
        return self._extract_endpoints_regex(content, ext, file_path)

    def _extract_endpoints_regex(self, content: str, ext: str, file_path: str) -> list:
        """正则表达式提取 API 端点"""
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
                    method = "GET"
                    path = groups[0]
                else:
                    continue

                line_num = content[:match.start()].count("\n") + 1
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
        """正则表达式提取数据模型"""
        models = []
        patterns = self.MODEL_PATTERNS.get(ext, [])
        lines = content.split("\n")

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                name = match.group(1)
                line_num = content[:match.start()].count("\n") + 1
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
        for i in range(start_idx + 1, min(start_idx + 5, len(lines))):
            line = lines[i].strip()
            if line.startswith('"""') or line.startswith("'''"):
                doc_lines = [line.lstrip('"\'')]
                for j in range(i + 1, min(i + 10, len(lines))):
                    doc_line = lines[j].strip()
                    doc_lines.append(doc_line)
                    if doc_line.endswith('"""') or doc_line.endswith("'''"):
                        break
                return " ".join(doc_lines).strip('"\' ')
            elif line.startswith("#"):
                return line.lstrip("# ").strip()
        return ""

    # ── 文件遍历 ──

    def _walk_files(self, repo: Path):
        """遍历仓库中的代码文件"""
        for path in repo.rglob("*"):
            if not path.is_file():
                continue
            if any(ignored in path.parts for ignored in self.ignore_dirs):
                continue
            if path.suffix in self.extensions:
                yield path
