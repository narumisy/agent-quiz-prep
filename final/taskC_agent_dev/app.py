"""Agent 命令行入口（可运行的程序）。

用法示例：
    python app.py --demo                       # 跑一组演示问答（便于截图）
    python app.py --query "产品的质保期是多久" # 单次问答
    python app.py                              # 交互式问答（/image 分析图片，/exit 退出）

依赖：见 requirements.txt；配置模型见 .env.example。
"""

import argparse
import sys

from exceptions import AgentError, friendly_error_message
from multimodal import analyze_image
from rag_agent import build_agent


def demo_questions():
    return [
        "产品的质保期是多久？",
        "设备开机后报 E102 错误，应该如何处理？",
        "你们什么时候推出 5G 版本？",
    ]


def run_demo(agent):
    print("\n========== 演示模式（模拟真实问答场景） ==========\n")
    for q in demo_questions():
        print(f"【用户】{q}\n")
        try:
            answer = agent.ask(q)
            print(f"【助手】{answer.text}\n")
            if answer.sources:
                print(f"【引用来源】{', '.join(answer.sources)}\n")
        except AgentError as exc:
            print(f"【助手】{friendly_error_message(exc)}\n")
        print("-" * 60, "\n")
    print("演示完成。可执行 `python app.py` 进入交互模式体验多轮对话。")


def run_interactive(agent):
    print("\n已进入交互模式。输入问题直接提问；输入 /image 图片路径 分析图片；/exit 退出。\n")
    while True:
        try:
            raw = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not raw:
            continue
        if raw.lower() in ("/exit", "/quit", "exit", "quit"):
            print("再见。")
            break
        if raw.startswith("/image"):
            parts = raw.split(maxsplit=1)
            if len(parts) < 2:
                print("用法：/image 图片路径 [附加问题]")
                continue
            seg = parts[1].split(" ", 1)
            img, question = seg[0], (seg[1] if len(seg) > 1 else "")
            try:
                print(f"\n助手 > {analyze_image(img, question)}\n")
            except AgentError as exc:
                print(f"\n助手 > {friendly_error_message(exc)}\n")
            continue
        try:
            answer = agent.ask(raw)
            print(f"\n助手 > {answer.text}\n")
            if answer.sources:
                print(f"引用来源 > {', '.join(answer.sources)}\n")
        except AgentError as exc:
            print(f"\n助手 > {friendly_error_message(exc)}\n")


def main():
    parser = argparse.ArgumentParser(description="RAG 知识问答 Agent")
    parser.add_argument("--docs", default="test_knowledge", help="知识文档目录")
    parser.add_argument("--init", action="store_true", help="强制重建知识库索引")
    parser.add_argument("--query", help="单次问答模式：直接传入问题")
    parser.add_argument("--image", help="图片分析模式：传入图片路径")
    parser.add_argument("--demo", action="store_true", help="演示模式：运行预设问答")
    args = parser.parse_args()

    try:
        if args.image:
            print(analyze_image(args.image))
            return
        agent = build_agent(docs_dir=args.docs)
    except (AgentError, FileNotFoundError, ValueError) as exc:
        print(f"[错误] {friendly_error_message(exc)}")
        sys.exit(1)

    try:
        if args.query:
            answer = agent.ask(args.query)
            print(f"问题：{args.query}\n\n{answer.text}\n")
            if answer.sources:
                print(f"引用来源：{', '.join(answer.sources)}")
        elif args.demo:
            run_demo(agent)
        else:
            run_interactive(agent)
    except AgentError as exc:
        print(f"[错误] {friendly_error_message(exc)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
