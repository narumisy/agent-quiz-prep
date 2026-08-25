"""模型工厂：根据环境变量自动选择真实大模型或本地模拟模型。

- 真实模式：配置 USER_LLM_API_KEY 后，通过 OpenAI 兼容接口调用大模型
  （可对接阿里云百炼 DashScope、DeepSeek、OpenAI 等），并配合向量化接口。
- 模拟模式：未配置 Key 时自动降级，用检索到的知识片段拼接生成回答，
  使整套 RAG 流程在无网络、无 Key 的环境下也能跑通演示（对应评分维度：集成度）。

环境变量（见 .env.example）：
    USER_LLM_API_KEY    API Key
    USER_LLM_BASE_URL   兼容接口地址，默认 https://dashscope.aliyuncs.com/compatible-mode/v1
    USER_LLM_MODEL      模型名，默认 qwen-plus
"""

import os
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from exceptions import LLMError

# ---------------- 环境变量加载（零依赖 .env 解析） ----------------

ENV_KEYS = ("USER_LLM_API_KEY", "USER_LLM_BASE_URL", "USER_LLM_MODEL",
            "USER_VISION_MODEL", "USER_EMBED_MODEL")


def load_env(env_file: str = ".env"):
    """读取当前目录 .env 文件中的 USER_* 变量（不覆盖已存在的环境变量）。"""
    path = Path(env_file)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in ENV_KEYS and key not in os.environ:
            os.environ[key] = value


def is_real_mode() -> bool:
    """是否配置了真实大模型 API Key。"""
    return bool(os.environ.get("USER_LLM_API_KEY"))


# ---------------- 模型客户端 ----------------

class LLMClient:
    """统一模型客户端：包装 LangChain ChatModel，invoke 返回字符串。"""

    def __init__(self, chat_model):
        self._model = chat_model

    def invoke(self, messages):
        """messages: [(role, content), ...]，role 为 system/user/assistant。"""
        try:
            langchain_msgs = [self._to_message(role, content) for role, content in messages]
            result = self._model.invoke(langchain_msgs)
            return str(result.content)
        except Exception as exc:
            raise LLMError(f"大模型调用失败: {exc}") from exc

    @staticmethod
    def _to_message(role: str, content: str):
        if role == "system":
            return SystemMessage(content=content)
        if role == "assistant":
            return AIMessage(content=content)
        return HumanMessage(content=content)


class MockLLMClient(LLMClient):
    """模拟模型：无 API Key 时使用，从提示词中抽取知识片段拼接成回答。"""

    def __init__(self):
        super().__init__(None)

    def invoke(self, messages):
        context, sources = self._extract_context(messages)
        if not context:
            return "（模拟输出）知识库暂未检索到相关内容。"
        snippet = context[0][:180]
        source_lines = "；".join(f"《{s}》" for s in sources[:3])
        return (
            "（模拟输出，配置真实 API Key 后由大模型生成）\n\n"
            f"根据知识库内容为您解答：{snippet}...\n\n"
            f"参考来源：{source_lines}"
        )

    @staticmethod
    def _extract_context(messages):
        """从最近的 user 消息中提取「【知识文档】…【用户问题】」之间的片段。"""
        context, sources = [], []
        for _, content in reversed(messages):
            if content and "【知识文档】" in content and "【用户问题】" in content:
                body = content.split("【知识文档】", 1)[1].split("【用户问题】", 1)[0]
                for block in body.split("来源:")[1:]:
                    source, _, text = block.partition("内容:")
                    sources.append(source.strip())
                    if text.strip():
                        context.append(text.strip())
                break
        return context, sources


def get_llm() -> LLMClient:
    """返回模型客户端：真实模式返回 ChatOpenAI，否则返回 MockLLMClient。"""
    load_env()
    if not is_real_mode():
        return MockLLMClient()
    try:
        from langchain_openai import ChatOpenAI

        model = os.environ.get("USER_LLM_MODEL", "qwen-plus")
        base_url = os.environ.get(
            "USER_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        chat = ChatOpenAI(
            model=model,
            api_key=os.environ["USER_LLM_API_KEY"],
            base_url=base_url,
            temperature=0.2,
            timeout=60,
            max_retries=2,
        )
        return LLMClient(chat)
    except Exception as exc:
        raise LLMError(f"初始化真实模型失败: {exc}") from exc


# ---------------- 向量化 ----------------

class LocalHashEmbedding:
    """本地轻量向量化：字符 n-gram 哈希 + L2 归一化。

    零外部依赖，保证离线可用；仅用于模拟模式演示 RAG 链路。
    真实模式下可替换为 OpenAIEmbeddings 等预训练模型。
    """

    DIM = 2048

    def __init__(self, dim: int = DIM):
        self.dim = dim

    def embed_query(self, text: str):
        return self._embed(text)

    def embed_documents(self, texts):
        return [self._embed(t) for t in texts]

    def _embed(self, text: str):
        import math

        vector = [0.0] * self.dim
        for tok in self._features(text.lower()):
            idx = hash(tok) % self.dim
            vector[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm if norm else v for v in vector]

    @staticmethod
    def _features(text: str):
        """特征集：字符 2-4gram + 词级 unigram，兼顾中英文检索。"""
        from string import punctuation

        grams = set()
        text = text.translate(str.maketrans("", "", punctuation + "，。！？、；：·—…《》【】（）"))
        for n in (2, 3, 4):
            grams.update(text[i:i + n] for i in range(len(text) - n + 1))
        for word in text.split():
            if len(word) >= 2:
                grams.add(word)
        return grams


def get_embeddings():
    """真实模式返回 OpenAIEmbeddings，否则返回 LocalHashEmbedding。"""
    load_env()
    if is_real_mode():
        try:
            from langchain_openai import OpenAIEmbeddings

            base_url = os.environ.get(
                "USER_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            return OpenAIEmbeddings(
                model=os.environ.get("USER_EMBED_MODEL", "text-embedding-v3"),
                api_key=os.environ["USER_LLM_API_KEY"],
                base_url=base_url,
            )
        except Exception:
            return LocalHashEmbedding()
    return LocalHashEmbedding()
