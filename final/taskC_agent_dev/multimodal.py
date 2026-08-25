"""多模态：图片理解能力（对应评分维度：多模态）。

- 真实模式：调用支持视觉的大模型（OpenAI 兼容接口，如 qwen-vl-plus / gpt-4o），
  将本地图片编码为 base64 后随文字问题一起发送，返回图片内容描述。
- 模拟模式：未配置 API Key 时返回图片文件信息与占位分析，保证流程可演示。
"""

import base64
import os
from pathlib import Path

from exceptions import ImageAnalysisError
from llm_factory import load_env

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

VISION_PROMPT = "请详细描述这张图片中的内容，如果包含文字请一并提取，并结合我的问题给出分析结论。"


def _encode_image(image_path: Path) -> tuple[str, str]:
    """返回 (data_uri, mime_type)。"""
    ext = image_path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ImageAnalysisError(
            f"不支持的图片格式 {ext}，支持：{', '.join(sorted(SUPPORTED_EXTS))}")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext.lstrip("."), f"image/{ext.lstrip('.')}")
    raw = image_path.read_bytes()
    if not raw:
        raise ImageAnalysisError("图片文件为空。")
    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{b64}", mime


def analyze_image(image_path: str, question: str = "", use_real: bool = None) -> str:
    """分析一张图片，返回描述结果。use_real=None 时自动按是否有 API Key 决定。"""
    path = Path(image_path)
    if not path.exists():
        raise ImageAnalysisError(f"图片文件不存在: {image_path}")
    if not path.is_file():
        raise ImageAnalysisError(f"路径不是文件: {image_path}")

    load_env()
    has_key = bool(os.environ.get("USER_LLM_API_KEY"))
    if use_real is None:
        use_real = has_key

    if not use_real:
        size_kb = path.stat().st_size / 1024
        return (
            "（模拟输出，配置真实视觉模型后可识别图片内容）\n"
            f"收到图片：{path.name}（{size_kb:.1f} KB）\n"
            "识别结果：本环境未配置多模态视觉模型，已正确接收图片并触发分析流程；"
            "配置 USER_LLM_API_KEY 与视觉模型（如 qwen-vl-plus / gpt-4o）后，"
            "此处将返回图片内容的真实识别与描述。"
        )

    try:
        from langchain_core.messages import HumanMessage
        from langchain_openai import ChatOpenAI

        model = os.environ.get("USER_VISION_MODEL") or os.environ.get(
            "USER_LLM_MODEL", "qwen-vl-plus")
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
        data_uri, _ = _encode_image(path)
        user_text = question.strip() or "请描述这张图片的内容。"
        message = HumanMessage(content=[
            {"type": "text", "text": f"{VISION_PROMPT}\n用户问题：{user_text}"},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ])
        result = chat.invoke([message])
        return str(result.content)
    except Exception as exc:
        raise ImageAnalysisError(f"多模态分析失败: {exc}") from exc
