# MiMo API Doc Agent

> 基于 MiMo 模型的多 Agent 协作 API 文档自动化生成与维护系统

## 🎯 解决的问题

在微服务架构下，API 文档严重滞后于代码变更，团队每月花费大量人力手动维护文档。本系统通过三个协作 Agent 实现文档的**零人工更新**。

## 🏗️ 架构设计

```
代码变更 (Git Push/PR Merge)
        │
        ▼
┌─────────────────┐
│   Parser Agent   │  ← 扫描代码，提取接口元信息
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generator Agent  │  ← 调用 MiMo 生成规范化文档
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Validator Agent  │  ← 校验文档与代码一致性
└────────┬────────┘
         │
         ▼
   生成修复 PR / 更新文档
```

### 三个 Agent

| Agent | 职责 | MiMo 用法 |
|-------|------|-----------|
| **Parser** | 扫描路由定义、注释、数据模型 | 代码语义理解 |
| **Generator** | 将元信息转化为规范文档 | 长上下文生成（中英文） |
| **Validator** | 对比历史版本，检测偏差 | 推理与一致性校验 |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入你的 MiMo API Key
```

### 3. 运行

```bash
# 对当前目录下的代码仓库生成文档
python main.py --repo ./your-project

# 指定输出目录
python main.py --repo ./your-project --output ./docs

# 仅解析（不调用 MiMo，用于调试）
python main.py --repo ./your-project --parse-only
```

### 4. GitHub Actions 自动化

将 `.github/workflows/doc-gen.yml` 复制到你的项目仓库，配置 `MIMO_API_KEY` secret 即可实现每次合并自动更新文档。

## 📁 项目结构

```
mimo-api-doc-agent/
├── main.py                  # 入口
├── config.yaml              # 配置文件
├── requirements.txt
├── agents/
│   ├── parser.py            # 解析 Agent
│   ├── generator.py         # 生成 Agent
│   └── validator.py         # 校验 Agent
├── core/
│   ├── orchestrator.py      # 多 Agent 编排器
│   └── mimo_client.py       # MiMo API 封装
├── templates/
│   └── api_doc.md.j2        # 文档模板
└── examples/
    └── sample_routes.py     # 示例代码（用于演示）
```

## 📊 效果

| 指标 | 使用前 | 使用后 |
|------|--------|--------|
| 文档更新延迟 | ~3 天 | 实时 |
| 月均维护工时 | ~40 人时 | ~2 人时 |
| 文档覆盖率 | ~60% | 98%+ |
| 日均 Token 消耗 | - | ~80 万 |

## License

MIT
