# 任务 C · 可运行 RAG 知识问答 Agent

> 对应评分维度：功能完整性、代码逻辑、集成度、多模态、异常机制。

## 功能概述

一个基于 LangChain + Python 的可运行 Agent：上传知识文档后，通过 **RAG 链路**
（文档加载 → 切分 → 向量化 → 相似度检索 → 大模型生成）实现知识问答，并支持：

- 多轮对话记忆（追问时自动结合上文）
- 多模态图片识别（/image 命令）
- 答案引用来源标注
- 统一的异常处理与重试机制
- 无 API Key 时自动降级为模拟模型，全流程离线可演示

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2.（可选）配置真实模型：复制 .env.example 为 .env 并填入 API Key
#    不配置则进入模拟模式

# 3. 演示模式（跑一组预设问答，可直接截图）
python app.py --demo

# 4. 单次问答
python app.py --query "设备的质保期是多久？"

# 5. 交互模式（多轮对话 + /image 图片分析）
python app.py
```

## 目录结构

| 文件 | 职责 |
|------|------|
| `app.py` | 命令行入口（--demo / --query / --image / 交互模式） |
| `rag_agent.py` | RAG 核心：知识库加载切分向量化检索、问答编排、多轮记忆 |
| `llm_factory.py` | 模型工厂：真实模型 / 模拟模型自动切换，向量化接口 |
| `multimodal.py` | 多模态图片理解 |
| `exceptions.py` | 统一异常类型与重试装饰器 |
| `test_knowledge/` | 测试知识文档（可替换为赛题文档） |
| `.env.example` | 模型配置占位模板 |

## 两种运行模式

| 模式 | 触发条件 | 说明 |
|------|----------|------|
| 真实模式 | 配置 `USER_LLM_API_KEY` | 调用真实大模型（百炼/DeepSeek/OpenAI 兼容接口）+ 真实向量化，回答质量高 |
| 模拟模式 | 未配置 Key | 使用本地哈希向量化 + 片段拼接回答，验证完整 RAG 流程，适合无网/无 Key 现场演示 |

## 现场适配赛题（3 步）

1. 将赛题提供的知识文档放入知识目录（如 `test_knowledge/`，支持 txt/md/pdf/docx）。
2. 运行 `python app.py --init` 重建索引（或直接启动自动重建）。
3. 用 3 类问题自测并截图：正常问答 / 无知识兜底 / 多轮追问，加 1 张 `/image` 图片分析截图。

## 评分点对照

| 评分维度 | 对应实现 |
|----------|----------|
| 功能完整性 | 加载→切分→检索→生成→引用→多轮→图片，全链路 |
| 代码逻辑 | 模块解耦（exceptions/llm_factory/rag_agent/multimodal/app），职责单一 |
| 集成度 | LangChain 组件（ChatOpenAI、RecursiveCharacterTextSplitter、消息构造）+ 可插拔向量化 |
| 多模态 | `multimodal.py` 图片 base64 + 视觉模型（qwen-vl-plus/gpt-4o） |
| 异常机制 | 分层异常类型、重试装饰器、知识库/检索/模型环节全覆盖、友好提示 |
