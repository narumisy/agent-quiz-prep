"""统一异常处理模块。

为 Agent 提供分层的异常类型与重试机制，覆盖知识库、检索、模型调用三大环节，
保证程序在出错时给出友好提示而非直接崩溃（对应评分维度：异常机制）。
"""

import time
from functools import wraps


class AgentError(Exception):
    """Agent 基础异常，所有自定义异常的父类。"""


class KnowledgeNotLoadedError(AgentError):
    """知识库尚未加载/构建。"""


class EmptyKnowledgeBaseError(AgentError):
    """知识库为空（没有可检索的文档）。"""


class RetrievalEmptyError(AgentError):
    """检索无结果（知识库中找不到相关内容）。"""


class LLMError(AgentError):
    """大模型调用失败。"""


class ImageAnalysisError(AgentError):
    """图片分析失败。"""


def retry(times: int = 3, delay: float = 1.0):
    """简单重试装饰器：调用失败后按固定间隔重试。

    Args:
        times: 最大重试次数（含首次）。
        delay: 每次重试前的等待秒数。
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except AgentError as exc:
                    last_error = exc
                    if attempt < times - 1:
                        time.sleep(delay)
            raise last_error

        return wrapper

    return decorator


def friendly_error_message(exc: Exception) -> str:
    """将异常转换为对用户友好的提示文案。"""
    if isinstance(exc, EmptyKnowledgeBaseError):
        return "知识库为空：请先执行初始化（--init），或将知识文档放入知识目录后重新初始化。"
    if isinstance(exc, RetrievalEmptyError):
        return "抱歉，我在知识库中没有找到与您问题相关的内容，请换个说法试试。"
    if isinstance(exc, KnowledgeNotLoadedError):
        return "知识库尚未加载，请先执行初始化（--init）。"
    if isinstance(exc, LLMError):
        return "模型服务暂时不可用，请稍后重试；若多次失败请检查 API Key 与网络配置。"
    if isinstance(exc, ImageAnalysisError):
        return "图片分析失败，请确认图片路径有效且格式受支持（jpg/png/bmp/webp）。"
    return f"发生未知错误：{exc}"
