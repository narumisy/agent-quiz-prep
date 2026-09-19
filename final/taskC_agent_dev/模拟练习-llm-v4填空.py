"""
模拟练习：LangChain 源码完形填空（基于示例llm-v4.py 挖空）
================================================================
用法：把每一处 FILL_XX 替换成你认为正确的值；全部填完后，
对照《模拟练习-答案与解析.md》批改。此文件刻意保持与考场主 py 同构：
环境变量预设、调用结构给定，你要填的是"参数值/名字/路径"。

挖空类型提示：
  FILL_XX         =  任意 Python 表达式（数字 / 字符串 / 布尔 / 变量名 / 函数名）
  "FILL_XX"       =  字符串常量（模型名 / URL 片段 / 字段名 / 键名）
"""

import os
import time
import unicodedata
import logging

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

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

SEP_MAJOR = "*" * 56
SEP_MINOR = "-" * 56


def print_banner(title: str) -> None:
    print(f"\n{SEP_MAJOR}\n  {title}\n{SEP_MAJOR}")


# ---------------------------------------------------------------- 1. 环境与网关配置
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

BASE_URL = "FILL_01"                      # ① OpenAI 兼容网关地址（末尾带 /v1）
API_KEY = INTERNAL_API_KEY
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# ---------------------------------------------------------------- 2. 飞书鉴权 + Aily 技能
_feishu_token_cache = {"token": None, "expire_at": 0.0}


def get_feishu_tenant_access_token() -> str:
    now = time.time()
    if _feishu_token_cache["token"] and now < _feishu_token_cache["expire_at"]:
        return _feishu_token_cache["token"]

    resp = requests.post(
        "FILL_02",                       # ② 飞书换取 tenant_access_token 的完整 URL
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=FILL_03,                 # ③ 鉴权请求超时（秒）
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败：{data}")

    token = data["FILL_04"]              # ④ token 所在的返回字段名
    _feishu_token_cache["token"] = token
    _feishu_token_cache["expire_at"] = now + int(data.get("expire", FILL_05)) - FILL_06
    return token                         # ⑤ 默认有效期(秒)  ⑥ 提前刷新余量(秒)


def call_aily_skill(query: str) -> str:
    token = get_feishu_tenant_access_token()
    url = (
        "FILL_07"                        # ⑦ 启动 Aily 技能的完整 URL 前缀（到 /start）
        f"{AILY_APP_ID}/skills/{AILY_SKILL_ID}/start"
    )
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {FILL_08}"},   # ⑧ Bearer 后的令牌变量
        json={FILL_09: {"query": query}},                 # ⑨ 技能入参的外层字段名
        timeout=FILL_10,                                  # ⑩ Aily 技能请求超时（秒，技能执行较慢）
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


# ---------------------------------------------------------------- 3. 大模型 (LLM)
llm = ChatOpenAI(
    model="FILL_11",                     # ⑪ 对话模型名
    temperature=FILL_12,                 # ⑫ 采样温度（更稳定取 0）
    base_url=BASE_URL,
    api_key=API_KEY,
)

# ---------------------------------------------------------------- 4. Embedding 向量模型
embeddings = OpenAIEmbeddings(
    model="FILL_13",                     # ⑬ 向量模型名
    base_url=BASE_URL,
    api_key=API_KEY,
    check_embedding_ctx_length=FILL_14,  # ⑭ 是否关闭 SDK 长度检查（配合较大文本关闭=False）
)

# ---------------------------------------------------------------- 5. 本地知识库 / RAG
PDF_PATH = os.path.join(os.path.dirname(__file__), "EOAI-知识库-v6.pdf")
PERSIST_DIR = os.path.join(os.path.dirname(__file__), "chroma_db_eoai")


def load_pdf_documents(pdf_path: str) -> list:
    reader = PdfReader(pdf_path)
    docs = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        text = unicodedata.normalize("FILL_15", text)      # ⑮ 兼容字符归一化模式
        if not text.strip():
            continue
        docs.append(Document(page_content=text,
                             metadata={"FILL_16": i, "FILL_17": pdf_path}))
    return docs                                            # ⑯ 页码键名  ⑰ 来源键名


def build_knowledge_base(pdf_path: str, persist_directory: str = PERSIST_DIR, k=FILL_18):
    docs = load_pdf_documents(pdf_path)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=FILL_19,              # ⑲ 每块大小（字符）
        chunk_overlap=FILL_20,           # ⑳ 相邻块重叠量（字符）
    )
    splits = text_splitter.split_documents(docs)
    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory=persist_directory,
    )
    return vectorstore.as_retriever(search_kwargs={"k": FILL_21})   # ㉑ 召回片段数 K


def get_or_build_retriever(pdf_path: str = PDF_PATH, persist_directory: str = PERSIST_DIR):
    chroma_sqlite = os.path.join(persist_directory, "FILL_22")       # ㉒ 判断建库的标志文件
    if os.path.exists(chroma_sqlite):
        vectorstore = Chroma(persist_directory=persist_directory, embedding_function=embeddings)
        return vectorstore.as_retriever(search_kwargs={"k": 4})
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"知识库 PDF 不存在：{pdf_path}")
    return build_knowledge_base(pdf_path, persist_directory)


retriever = get_or_build_retriever()

# ---------------------------------------------------------------- 6. Tools
@tool
def search_knowledge_base(query: str) -> str:
    """检索企业内部 EOAI 知识库，覆盖企业概况、经营数据、战略工程等。输入为检索关键词或问题摘要。"""
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
def FILL_23(query: str) -> str:
    """检索飞书 Aily 企业内部知识库/工作流（企业 RAG），适合制度流程、内部文档与业务问答。输入为自然语言问题。"""
    return call_aily_skill(query)        # ㉓ 飞书 Aily 工具的函数名


@tool
def search_external_cases(query: str) -> str:
    """检索外部公开信息，适合行业案例、实时动态，或内部资料未覆盖的内容。输入为搜索关键词。"""
    data = tavily_client.search(
        query=query,
        max_results=FILL_24,             # ㉔ 结果条数上限
        search_depth="FILL_25",          # ㉕ 检索深度
        include_answer=FILL_26,          # ㉖ 是否额外生成摘要答案
    )
    results = data.get("FILL_27") or []  # ㉗ Tavily 返回中存放结果列表的字段
    if not results:
        return "外部检索未找到相关结果。"
    parts = []
    for i, item in enumerate(results, 1):
        title = item.get("FILL_28") or "无标题"   # ㉘ 结果标题字段
        url = item.get("FILL_29") or ""           # ㉙ 结果链接字段
        content = (item.get("FILL_30") or "").strip()  # ㉚ 结果摘要字段
        parts.append(f"[{i}] {title}\n来源: {url}\n摘要: {content}")
    return "\n\n".join(parts)


tools = [search_knowledge_base, FILL_31, search_external_cases]
                                                       # ㉛ 中间那个工具的变量名

# ---------------------------------------------------------------- 7. 系统提示词
SYSTEM_PROMPT = (
    "你是知识检索助手：帮用户查找并整理信息，再给出清晰、有依据的回答。"
    "你可以按需使用可用工具检索内部或外部资料；是否检索、检索哪里，由你根据问题自行判断。"
    "有检索结果时优先依据结果作答，并简要说明信息来源；没有合适资料时坦诚说明，不要编造。"
)

# ---------------------------------------------------------------- 8. 组装 Agent
checkpointer = FILL_32()                 # ㉜ 内存型记忆类（函数名）
agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
    debug=FILL_33,                       # ㉝ 是否开启图执行调试日志（演示关闭=False）
)

SESSION_CONFIG = {"configurable": {"thread_id": "FILL_34"}}   # ㉞ 会话线程 id


def messages_for_this_turn(result: dict) -> list:
    messages = result.get("messages") or []
    last_human_idx = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            last_human_idx = i
    return messages[last_human_idx:] if last_human_idx >= 0 else messages


def summarize_tool_calls(turn_messages: list) -> list:
    names = []
    for msg in turn_messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name and name not in names:
                    names.append(name)
    return names


def extract_final_reply(result: dict) -> str:
    for msg in reversed(messages_for_this_turn(result)):
        if isinstance(msg, AIMessage) and msg.content:
            if getattr(msg, "tool_calls", None) and not str(msg.content).strip():
                continue
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return ""


# ---------------------------------------------------------------- 9. 交互入口
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

        print(SEP_MINOR, "\n  Agent 处理中…\n", SEP_MINOR)
        result = agent.invoke(
            {"messages": [{"role": "FILL_35", "content": user_input}]},   # ㉟ 消息角色
            config=SESSION_CONFIG,
        )
        used_tools = summarize_tool_calls(messages_for_this_turn(result))
        print(f"  本轮调用工具：{', '.join(used_tools)}" if used_tools else "  本轮未调用工具（模型直接作答）")

        print(SEP_MINOR, "\n  助手回答\n", SEP_MINOR)
        print(extract_final_reply(result))
        print(SEP_MAJOR)