"""提示词工程 AI 评分服务（比赛备考工具）

功能：
  - GET  /                   静态文件服务（index.html / scorer.js / quiz.html 等）
  - GET  /api/questions      返回题库列表（id/title/difficulty/tags/focus/task/analysis）
  - POST /api/score          接收 System Prompt + 可选 question_id，
                             按题库对应《本题考察重点》驱动 8 维评分
                             （维度打分 + 总评 + 优点 + 改进建议 + 题目解析），失败自动重试

运行：python3 scorer_server.py  （默认 8000 端口，可用 --port 修改）
依赖：仅 Python 标准库。
"""

import json
import os
import re
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prompt_questions import QUESTIONS, get_question

# ---------------------------------------------------------------- 配置
BASE_URL = "https://token.sensenova.cn/v1/chat/completions"
API_KEY = "sk-inm8NgabNcg1LsXZLjJMEwDQkU4naK7D"
MODEL = "deepseek-v4-flash"

WORKSPACE = Path(__file__).resolve().parent

# 模型调用参数
REQUEST_TIMEOUT = 90
MAX_RETRIES = 3          # 调用失败自动重试次数（不含首次）
RETRY_BASE_DELAY = 1.5   # 指数退避基数（秒）

# ---------------------------------------------------------------- 评分模型（8 维，权重合计 100）
DIMENSIONS = [
    {"id": "role",    "name": "角色与定位设定", "weight": 10,
     "rubric": "是否明确设定助手角色（身份/职责/服务对象）；角色与任务是否匹配；是否说明能力边界。"},
    {"id": "task",    "name": "任务明确性", "weight": 15,
     "rubric": "是否清晰说明要完成什么任务、一次对话内按什么顺序完成多个子任务；任务目标是否无歧义。"},
    {"id": "structure", "name": "指令结构化", "weight": 15,
     "rubric": "提示词是否有清晰的逻辑组织（分节/编号/分隔符/优先级）；指令层级是否分明，便于模型逐步执行。"},
    {"id": "context", "name": "上下文完整性", "weight": 10,
     "rubric": "是否提供完成任务所需的背景信息（产品/场景/目标用户/参考数据）；上下文是否充分且相关。"},
    {"id": "constraints", "name": "约束条件明确性", "weight": 15,
     "rubric": "输出约束是否明确具体（长度限制、内容禁忌、不编造、术语一致）；边界规则（如产品名不符时的处理）是否写清。"},
    {"id": "format",  "name": "输出格式规范", "weight": 15,
     "rubric": "是否指定输出格式（如 JSON schema/字段定义/Markdown 结构）；是否强调'程序可直接解析、禁止多余内容'。"},
    {"id": "edge",    "name": "边界与异常处理", "weight": 10,
     "rubric": "是否覆盖边界/异常情形（非法输入、无相关知识、话题越界、用户提问与任务无关等）并给出固定回复。"},
    {"id": "example", "name": "示例与稳健性", "weight": 10,
     "rubric": "是否提供 few-shot 示例引导输出（含命中/未命中两种情形）；表达是否简洁、可复用、具备防注入等稳健考虑。"},
]
WEIGHT_SUM = sum(d["weight"] for d in DIMENSIONS)

DEFAULT_TASK = QUESTIONS[0]["task"]

SCORE_SYSTEM_PROMPT = """你是提示词工程（Prompt Engineering）资深评审专家。请依据业界公认的提示词工程规范，
对用户提供的 System Prompt（系统提示词）进行专业评分。

评分遵循以下 8 个维度（权重合计 100），每个维度按 0-100 打分，90-100 为优秀，75-89 为良好，
60-74 为及格，0-59 为不合格：

{dimension_spec}

{question_spec}

评分原则：
1. 严格对照【题目要求】逐项核查：是否满足所有硬性要求（子任务顺序、字数限制、JSON 输出、边界分支）。
2. 按【本题考察要点】逐条核查提示词是否覆盖；覆盖越全、表达越具体可执行，相应维度得分越高。
3. 结构越清晰、约束越具体、示例越充分，得分越高；内容空泛、缺角色、无输出格式约束、漏边界处理的，相应维度扣分。
4. 每个维度的 comment 用一句中文点评，说明得分理由；不要输出 JSON 之外的内容。
5. 若提示词在本题考察要点上存在明显缺失（如完全没有 JSON 输出要求、完全没处理边界分支），在 improvements 中明确指出。
6. 最终按加权计算 overall（四舍五入到整数），并给出等级：A(≥90) B(≥75) C(≥60) D(<60)。

必须严格按以下 JSON 结构输出，禁止输出任何非 JSON 文本：

{{
  "overall": <加权总分 0-100>,
  "level": "<A|B|C|D>",
  "dimensions": [
    {{"id": "role", "score": <0-100>, "comment": "<中文点评>"}},
    {{"id": "task", "score": <0-100>, "comment": "<中文点评>"}},
    {{"id": "structure", "score": <0-100>, "comment": "<中文点评>"}},
    {{"id": "context", "score": <0-100>, "comment": "<中文点评>"}},
    {{"id": "constraints", "score": <0-100>, "comment": "<中文点评>"}},
    {{"id": "format", "score": <0-100>, "comment": "<中文点评>"}},
    {{"id": "edge", "score": <0-100>, "comment": "<中文点评>"}},
    {{"id": "example", "score": <0-100>, "comment": "<中文点评>"}}
  ],
  "strengths": ["<优点1>", "<优点2>"],
  "improvements": ["<改进建议1>", "<改进建议2>"],
  "summary": "<50-120字总体评价>",
  "focus_check": [{{"point": "<本题考察要点条文>", "covered": true, "note": "<核查说明>"}}]
}}"""


def build_focus_check(points_text: str) -> str:
    """把多行考察要点转成前端可渲染的核查清单文本。"""
    items = []
    for line in points_text.splitlines():
        line = line.strip().lstrip("1.234567890)）·-")
        if line:
            items.append(line)
    return "\n".join(f"- {it}" for it in items) or "（未提供考察要点）"


def build_user_prompt(task: str, prompt: str) -> str:
    return f"""【题目要求】
{task}

【待评分的 System Prompt】
```
{prompt}
```

请按评分规范对上述 System Prompt 评分，输出严格 JSON。"""


# ---------------------------------------------------------------- AI 调用（含重试）
def call_llm(prompt_text: str, question: dict = None) -> dict:
    """调用大模型，自动重试，返回解析后的 JSON。question 为题库项（含 focus）时注入考察要点。"""
    dimension_spec = "\n".join(
        f'- {d["name"]}（权重 {d["weight"]}%）：{d["rubric"]}' for d in DIMENSIONS)

    if question and question.get("focus"):
        question_spec = (
            "【本题考察要点】（评分时必须逐条核查，作为各维度打分的主要依据）：\n"
            + build_focus_check(question["focus"]))
    else:
        question_spec = "【本题考察要点】无特别指定时，按通用提示词工程规范审查。"

    system = SCORE_SYSTEM_PROMPT.format(dimension_spec=dimension_spec,
                                        question_spec=question_spec)
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt_text},
        ],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                BASE_URL, data=data,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {API_KEY}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            content = body["choices"][0]["message"]["content"]
            parsed = extract_json(content)
            if parsed is not None:
                return parsed
            last_error = ValueError(f"模型返回无法解析为 JSON：{content[:200]}")
        except Exception as exc:  # 网络/HTTP/解析错误统一捕获
            last_error = exc
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

    raise RuntimeError(f"AI 评分调用失败（已重试 {MAX_RETRIES} 次）：{last_error}")


def extract_json(content: str):
    """从模型输出中提取 JSON 对象（容忍前后包裹文本/代码块）。"""
    if not isinstance(content, str):
        return None
    text = content.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    return None


def normalize_result(raw: dict) -> dict:
    """校验并对齐评分结果，保证前端渲染不报错。"""
    dim_map = {d["id"]: d for d in DIMENSIONS}
    normalized_dims = []
    for d in DIMENSIONS:
        found = None
        if isinstance(raw.get("dimensions"), list):
            for item in raw["dimensions"]:
                if isinstance(item, dict) and item.get("id") == d["id"]:
                    found = item
                    break
        score = found.get("score") if isinstance(found, dict) else None
        try:
            score = max(0, min(100, int(round(float(score)))))
        except (TypeError, ValueError):
            score = 0
        comment = found.get("comment", "") if isinstance(found, dict) else ""
        normalized_dims.append({"id": d["id"], "name": d["name"],
                                "weight": d["weight"], "score": score, "comment": comment})

    overall = raw.get("overall")
    try:
        overall = max(0, min(100, int(round(float(overall)))))
    except (TypeError, ValueError):
        overall = round(sum(d["score"] * d["weight"] for d in normalized_dims) / WEIGHT_SUM)

    level = str(raw.get("level") or "").strip().upper()
    if level not in ("A", "B", "C", "D"):
        level = "A" if overall >= 90 else "B" if overall >= 75 else "C" if overall >= 60 else "D"

    def clean_list(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()][:5]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    focus_check = []
    if isinstance(raw.get("focus_check"), list):
        for item in raw["focus_check"][:12]:
            if isinstance(item, dict):
                covered = item.get("covered") in (True, "true", "True", 1, "是", "有", "yes")
                focus_check.append({
                    "point": str(item.get("point") or "").strip(),
                    "covered": covered,
                    "note": str(item.get("note") or "").strip(),
                })
    # 去掉空 point 条目
    focus_check = [f for f in focus_check if f["point"]]

    return {
        "overall": overall,
        "level": level,
        "dimensions": normalized_dims,
        "strengths": clean_list(raw.get("strengths")),
        "improvements": clean_list(raw.get("improvements")),
        "summary": str(raw.get("summary") or "").strip(),
        "model": MODEL,
        "focus_check": focus_check,
    }


# ---------------------------------------------------------------- HTTP 服务
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 精简日志
        sys.stderr.write("[%s] %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/questions":
            self._send_json({"questions": [
                {"id": q["id"], "title": q["title"], "difficulty": q["difficulty"],
                 "tags": q.get("tags", []), "focus": q["focus"], "task": q["task"],
                 "analysis": q["analysis"]} for q in QUESTIONS]})
            return
        if path in ("/", "/index.html"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")
        target = (WORKSPACE / rel).resolve()
        if not str(target).startswith(str(WORKSPACE)) or not target.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/score":
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._send_json({"error": "请求体不是合法 JSON"}, 400)
            return

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            self._send_json({"error": "缺少 prompt 参数"}, 400)
            return

        qid = (body.get("question_id") or "").strip()
        question = get_question(qid) if qid else None

        # 任务优先级：请求体明文 task > 题目库 task > 默认
        task = (body.get("task") or "").strip()
        if not task:
            task = question["task"] if question else DEFAULT_TASK

        try:
            raw = call_llm(build_user_prompt(task, prompt), question=question)
            result = normalize_result(raw)
            result["prompt_len"] = len(prompt)
            if question:
                result["question"] = {
                    "id": question["id"],
                    "title": question["title"],
                    "difficulty": question["difficulty"],
                    "tags": question.get("tags", []),
                    "analysis": question["analysis"],
                }
            else:
                result["question"] = None
            self._send_json(result)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)


def main():
    port = 8000
    if "--port" in sys.argv:
        try:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        except (ValueError, IndexError):
            pass
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"提示词评分服务已启动：http://0.0.0.0:{port}  （model={MODEL}）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
