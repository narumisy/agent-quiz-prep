"""
知识检索助手示例（llm-v4.py）
================================

相对 llm-v3.py：
1. 去掉 langchain-community（改用 pypdf 直接读 PDF），消除 sunset 告警
2. 关闭 create_agent(debug=True) 等嘈杂调试输出，优化培训演示终端体验
3. 用清晰的分隔线划分「提问 / 工具 / 回答」板块

整体流水线与 v3 相同：create_agent + MemorySaver + Tools。
"""

import os
import time
import unicodedata
import logging

# ---------------------------------------------------------------------------
# 依赖说明
# ---------------------------------------------------------------------------
# ChatOpenAI / OpenAIEmbeddings：对接 OpenAI 兼容网关（企业内部 MaaS）
# pypdf + Document：本地 PDF 加载（不再依赖已 sunset 的 langchain-community）
# TextSplitter / Chroma：切分与向量库
# TavilyClient：外部网页检索
# 飞书 Aily 技能 API：企业内部 RAG / Workflow
# create_agent：LangChain 1.x 推荐的 Agent 工厂（返回 LangGraph 图）
# MemorySaver：内存型 checkpointer，按 thread_id 持久化对话状态
#
# 文档：https://docs.langchain.com/oss/python/langchain/agents
import requests
from dotenv import load_dotenv
from pypdf import PdfReader
from tavily import TavilyClient
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_core.tools import tool
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

# 培训演示时压低第三方库日志，避免刷屏
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("langchain").setLevel(logging.WARNING)
logging.getLogger("langgraph").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# 终端展示辅助（培训演示用）
# ---------------------------------------------------------------------------
SEP_MAJOR = "*" * 56
SEP_MINOR = "-" * 56


def print_banner(title: str) -> None:
    print(f"\n{SEP_MAJOR}")
    print(f"  {title}")
    print(SEP_MAJOR)


def print_section(title: str) -> None:
    print(f"\n{SEP_MINOR}")
    print(f"  {title}")
    print(SEP_MINOR)


# ---------------------------------------------------------------------------
# 1. 环境与网关配置
# ---------------------------------------------------------------------------
# 密钥放在项目根目录 .env（已 gitignore），勿把 Key 提交到仓库。
load_dotenv()

INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET")
AILY_APP_ID = os.environ.get("AILY_APP_ID")
AILY_SKILL_ID = os.environ.get("AILY_SKILL_ID")

_required = {
    "INTERNAL_API_KEY": INTERNAL_API_KEY,
    "TAVILY_API_KEY": TAVILY_API_KEY,
    "FEISHU_APP_ID": FEISHU_APP_ID,
    "FEISHU_APP_SECRET": FEISHU_APP_SECRET,
    "AILY_APP_ID": AILY_APP_ID,
    "AILY_SKILL_ID": AILY_SKILL_ID,
}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    raise RuntimeError(f"缺少环境变量：{', '.join(_missing)}，请在 .env 中配置")

# OpenAI 兼容接口的 base_url（末尾带 /v1，不要再拼 /chat/completions）
BASE_URL = "https://maas-test.sgmw.com.cn/v1"
API_KEY = INTERNAL_API_KEY
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# ---------------------------------------------------------------------------
# 飞书开放平台 / Aily 调用说明
# ---------------------------------------------------------------------------
# 调用链路（两步）：
#   1) 用 FEISHU_APP_ID + FEISHU_APP_SECRET 换取 tenant_access_token
#      POST /open-apis/auth/v3/tenant_access_token/internal
#   2) 携带 Bearer token，同步启动 Aily Workflow 技能
#      POST /open-apis/aily/v1/apps/{AILY_APP_ID}/skills/{AILY_SKILL_ID}/start
#         body: {"global_variable": {"query": "<用户问题>"}}
#      文档：https://open.feishu.cn/document/aily-v1/app-skill/start
#
# 环境变量：FEISHU_APP_ID / FEISHU_APP_SECRET / AILY_APP_ID / AILY_SKILL_ID
# 权限：应用需开通「运行技能」aily:skill:write，并在 Aily「开放接入」允许应用身份调用。

_feishu_token_cache = {"token": None, "expire_at": 0.0}


def get_feishu_tenant_access_token() -> str:
    """获取飞书应用身份 token（tenant_access_token），供后续 Aily OpenAPI 鉴权。"""
    now = time.time()
    if _feishu_token_cache["token"] and now < _feishu_token_cache["expire_at"]:
        return _feishu_token_cache["token"]

    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=30,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败：{data}")

    token = data["tenant_access_token"]
    _feishu_token_cache["token"] = token
    _feishu_token_cache["expire_at"] = now + int(data.get("expire", 7200)) - 60
    return token


def call_aily_skill(query: str) -> str:
    """调用飞书 Aily Workflow 技能（企业 RAG），同步返回技能执行结果。"""
    token = get_feishu_tenant_access_token()
    url = (
        f"https://open.feishu.cn/open-apis/aily/v1/apps/"
        f"{AILY_APP_ID}/skills/{AILY_SKILL_ID}/start"
    )
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"global_variable": {"query": query}},
        timeout=120,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Aily 技能调用失败：{data}")

    payload = data.get("data") or {}
    output = payload.get("output")
    status = payload.get("status")
    if output:
        return output if isinstance(output, str) else str(output)
    return f"Aily 执行完成（status={status}），但未返回 output：{payload}"


# ---------------------------------------------------------------------------
# 2. 大模型（LLM）
# ---------------------------------------------------------------------------
llm = ChatOpenAI(
    model="deepseek-v4-flash",
    temperature=0,
    base_url=BASE_URL,
    api_key=API_KEY,
)

# ---------------------------------------------------------------------------
# 3. Embedding 模型
# ---------------------------------------------------------------------------
embeddings = OpenAIEmbeddings(
    model="bge-m3",
    base_url=BASE_URL,
    api_key=API_KEY,
    check_embedding_ctx_length=False,
)


# ---------------------------------------------------------------------------
# 4. 本地知识库 / RAG
# ---------------------------------------------------------------------------
# 用 pypdf.PdfReader 直接读页，组装为 langchain Document，避免 langchain-community。
PDF_PATH = os.path.join(os.path.dirname(__file__), "EOAI-知识库-v6.pdf")
PERSIST_DIR = os.path.join(os.path.dirname(__file__), "chroma_db_eoai")


def load_pdf_documents(pdf_path: str) -> list[Document]:
    """用 pypdf 按页加载 PDF，并做 NFKC 归一化。"""
    reader = PdfReader(pdf_path)
    docs: list[Document] = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        text = unicodedata.normalize("NFKC", text)
        if not text.strip():
            continue
        docs.append(Document(page_content=text, metadata={"page": i, "source": pdf_path}))
    return docs


def build_knowledge_base(
    pdf_path: str, persist_directory: str = PERSIST_DIR, k: int = 4
):
    """加载离线资料并构建本地向量数据库，返回 Retriever。"""
    docs = load_pdf_documents(pdf_path)
    print(f"  已加载 PDF：{os.path.basename(pdf_path)}（共 {len(docs)} 页有效文本）")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, chunk_overlap=100
    )
    splits = text_splitter.split_documents(docs)
    print(f"  切分为 {len(splits)} 个文本块，写入向量库…")

    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory=persist_directory,
    )
    print("  向量库构建完成")
    return vectorstore.as_retriever(search_kwargs={"k": k})


def get_or_build_retriever(pdf_path: str = PDF_PATH, persist_directory: str = PERSIST_DIR):
    """若本地已有向量库则直接加载，否则从 PDF 新建。"""
    chroma_sqlite = os.path.join(persist_directory, "chroma.sqlite3")
    if os.path.exists(chroma_sqlite):
        print("  本地向量库已就绪，直接加载")
        vectorstore = Chroma(
            persist_directory=persist_directory,
            embedding_function=embeddings,
        )
        return vectorstore.as_retriever(search_kwargs={"k": 4})
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"知识库 PDF 不存在：{pdf_path}")
    return build_knowledge_base(pdf_path, persist_directory)


print_section("初始化知识库")
retriever = get_or_build_retriever()


# ---------------------------------------------------------------------------
# 5. Tools
# ---------------------------------------------------------------------------
@tool
def search_knowledge_base(query: str) -> str:
    """检索企业内部 EOAI 知识库，覆盖上汽通用五菱相关的企业概况、经营数据、
    战略工程、技术品牌与产品资料等。输入为检索关键词或问题摘要。"""
    docs = retriever.invoke(query)
    if not docs:
        return "知识库未检索到相关内容。"
    parts = []
    for i, doc in enumerate(docs, 1):
        page = doc.metadata.get("page")
        page_label = f"第{page + 1}页" if isinstance(page, int) else "未知页"
        parts.append(f"[{i}] ({page_label})\n{doc.page_content}")
    return "\n\n".join(parts)


@tool
def search_aily_rag(query: str) -> str:
    """检索飞书 Aily 企业内部知识库/工作流（企业 RAG）。
    适合制度流程、内部文档、已接入 Aily 的业务问答。输入为自然语言问题。"""
    try:
        return call_aily_skill(query)
    except Exception as e:
        return f"Aily 检索失败：{e}"


@tool
def search_external_cases(query: str) -> str:
    """检索外部公开信息，适合行业案例、实时动态，或内部资料未覆盖的内容。输入为搜索关键词。"""
    try:
        data = tavily_client.search(
            query=query,
            max_results=5,
            search_depth="basic",
            include_answer=False,
        )
    except Exception as e:
        return f"外部检索失败：{e}"

    results = data.get("results") or []
    if not results:
        return "外部检索未找到相关结果。"

    parts = []
    for i, item in enumerate(results, 1):
        title = item.get("title") or "无标题"
        url = item.get("url") or ""
        content = (item.get("content") or "").strip()
        parts.append(f"[{i}] {title}\n来源: {url}\n摘要: {content}")
    return "\n\n".join(parts)


tools = [search_knowledge_base, search_aily_rag, search_external_cases]

# ---------------------------------------------------------------------------
# 6. System Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "你是知识检索助手：帮用户查找并整理信息，再给出清晰、有依据的回答。"
    "你可以按需使用可用工具检索内部或外部资料；是否检索、检索哪里，由你根据问题自行判断。"
    "有检索结果时优先依据结果作答，并简要说明信息来源；没有合适资料时坦诚说明，不要编造。"
)

# ---------------------------------------------------------------------------
# 7. 组装 Agent
# ---------------------------------------------------------------------------
# debug=False：关闭图执行细节 / token 用量等调试刷屏，适合培训演示
checkpointer = MemorySaver()
agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
    debug=False,
)

SESSION_CONFIG = {"configurable": {"thread_id": "cli-session"}}


def messages_for_this_turn(result: dict) -> list:
    """只取本轮（最近一条 HumanMessage 之后）的消息，避免把历史整段重打一遍。"""
    messages = result.get("messages") or []
    last_human_idx = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            last_human_idx = i
    if last_human_idx < 0:
        return messages
    return messages[last_human_idx:]


def summarize_tool_calls(turn_messages: list) -> list[str]:
    """汇总本轮调用过的工具名（去重保序），便于演示时一眼看到 Agent 行为。"""
    names: list[str] = []
    for msg in turn_messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name and name not in names:
                    names.append(name)
    return names


def extract_final_reply(result: dict) -> str:
    """取出本轮最后一条有文本内容的 AIMessage。"""
    for msg in reversed(messages_for_this_turn(result)):
        if isinstance(msg, AIMessage) and msg.content:
            if getattr(msg, "tool_calls", None) and not str(msg.content).strip():
                continue
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


# ---------------------------------------------------------------------------
# 8. 交互入口 —— 培训演示友好的 CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print_banner("知识检索助手 v4")
    print("  可用能力：本地 PDF 知识库 / 飞书 Aily / Tavily 公网搜索")
    print("  输入问题开始对话；输入 exit 或 quit 退出")
    print(SEP_MAJOR)

    while True:
        user_input = input("\n你: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ["exit", "quit"]:
            print_banner("会话结束，再见！")
            break

        print_section("Agent 处理中…")
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config=SESSION_CONFIG,
        )

        turn_msgs = messages_for_this_turn(result)
        used_tools = summarize_tool_calls(turn_msgs)
        if used_tools:
            print(f"  本轮调用工具：{', '.join(used_tools)}")
        else:
            print("  本轮未调用工具（模型直接作答）")

        # 可选：简要列出工具返回是否成功（不打印全文/token）
        tool_msgs = [m for m in turn_msgs if isinstance(m, ToolMessage)]
        for tm in tool_msgs:
            name = getattr(tm, "name", None) or "tool"
            preview = (tm.content or "").replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:80] + "…"
            print(f"  · {name} → {preview}")

        print_section("助手回答")
        print(extract_final_reply(result))
        print(SEP_MAJOR)
