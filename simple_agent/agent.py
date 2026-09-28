#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小可用 Agent 实验

Agent = 模型 + 工具 + 一个循环。模型不会执行代码，它只会说"我要调用某个工具"，
真正执行的是下面这个 while 循环；把结果塞回对话再问它一次，直到它不要工具为止。

用法：
    python3 agent.py                        # 交互模式
    python3 agent.py -q "现在几点？算一下 (128*37+15)/7"   # 单次提问
    python3 agent.py --selftest             # 离线自测（不调用 API，不花钱）
"""
import argparse
import ast
import datetime
import json
import operator
import re
import sys
from pathlib import Path

import config

# 配置（API Key、模型、接口地址）全部在 config.py + .env 里，本文件不含密钥

# 运行参数：与密钥无关，留在本文件方便随手调
MAX_STEPS = 8         # 单个问题的最大循环步数，防止无限调用工具
TEMPERATURE = 0.7     # 越高越发散，越低越稳定

NOTES_DIR = Path(__file__).resolve().parent / "notes"
SYSTEM_PROMPT = """你是一个能动手的助手，用中文回答。

规则：
- 需要算术、当前时间、读写笔记时，必须调用工具，不要凭记忆猜。
- 一次只做一件事，拿到工具结果后再决定下一步。
- 最后用一两句话总结你做了什么、结果是什么，不要复述工具日志。"""


# ------------------------------------------------------------------ 工具
# 工具就是普通函数：收参数，返回字符串。返回值会原样给模型看，所以要写成人能读的话。
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.USub: operator.neg, ast.FloorDiv: operator.floordiv}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("只支持数字和 + - * / // % ** 运算")


def calculator(expression):
    """计算数学表达式，例如 (128*37+15)/7。"""
    return _eval(ast.parse(expression, mode="eval").body)


def get_time():
    """返回当前本地日期时间。"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_note(title, content):
    """把一条笔记存到 notes/ 目录。"""
    NOTES_DIR.mkdir(exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "-", title).strip().strip(".") or "note"
    path = NOTES_DIR / ("%s.md" % safe)
    path.write_text("# %s\n\n%s\n" % (title, content), encoding="utf-8")
    return "已保存到 %s" % path.name


def list_notes():
    """列出已保存的笔记。"""
    if not NOTES_DIR.exists():
        return "（还没有任何笔记）"
    files = sorted(NOTES_DIR.glob("*.md"))
    return "\n".join("- %s" % f.stem for f in files) if files else "（还没有任何笔记）"


# 告诉模型有哪些工具（JSON Schema：名字、用途、参数）
TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "calculator", "description": "计算数学表达式，例如 (128*37+15)/7",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string", "description": "要计算的表达式"}},
                       "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "get_time", "description": "获取当前本地日期时间",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "save_note", "description": "把一条笔记保存到本地 notes 目录",
        "parameters": {"type": "object",
                       "properties": {"title": {"type": "string", "description": "笔记标题，会作为文件名"},
                                      "content": {"type": "string", "description": "笔记正文"}},
                       "required": ["title", "content"]}}},
    {"type": "function", "function": {
        "name": "list_notes", "description": "列出已保存的笔记标题",
        "parameters": {"type": "object", "properties": {}}}},
]

TOOLS_IMPL = {"calculator": calculator, "get_time": get_time,
              "save_note": save_note, "list_notes": list_notes}


def run_tool(name, arguments):
    """执行工具。任何出错都变成一段文字返回给模型，绝不让循环崩掉。"""
    func = TOOLS_IMPL.get(name)
    if func is None:
        return "没有这个工具：%s。可用工具：%s" % (name, "、".join(TOOLS_IMPL))
    try:
        return str(func(**arguments))
    except TypeError as exc:
        return "参数不对：%s。请检查参数名后重试。" % exc
    except Exception as exc:
        return "%s: %s" % (type(exc).__name__, exc)


# ------------------------------------------------------------------ 模型
def ask_model(messages, tools):
    """调用 DeepSeek，返回 (文字, 工具调用列表)。这是唯一和具体模型有关的地方。"""
    from openai import OpenAI

    client = OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL, timeout=60)
    resp = client.chat.completions.create(model=config.MODEL, messages=messages,
                                          tools=tools or None, temperature=TEMPERATURE)
    msg = resp.choices[0].message
    calls = []
    for call in (msg.tool_calls or []):
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {"_原始参数": call.function.arguments}   # 参数坏了也让模型看到，它能自己修
        calls.append({"id": call.id, "name": call.function.name, "args": args})
    return msg.content or "", calls


# ------------------------------------------------------------------ 循环
def run(question, messages=None, model=None, verbose=True):
    """Agent 主循环：问模型 -> 要工具就执行 -> 结果塞回对话 -> 再问，直到它不要工具。"""
    model = model or ask_model
    messages = list(messages or [{"role": "system", "content": SYSTEM_PROMPT}])
    messages.append({"role": "user", "content": question})

    for step in range(1, MAX_STEPS + 1):
        text, calls = model(messages, TOOLS_SCHEMA)

        if not calls:                      # 收工条件：模型不再要工具
            messages.append({"role": "assistant", "content": text})
            if verbose:
                print("  （用了 %d 步）" % step)
            return text, messages

        messages.append({"role": "assistant", "content": text or None, "tool_calls": [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
            for c in calls]})

        for call in calls:
            result = run_tool(call["name"], call["args"])
            if verbose:
                print("  → %s(%s) = %s" % (call["name"],
                                           json.dumps(call["args"], ensure_ascii=False)[:80],
                                           result[:120].replace("\n", " ")))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})

    return "（达到最大步数 %d，没能得出结论）" % MAX_STEPS, messages


# ------------------------------------------------------------------ 离线自测
class FakeModel:
    """假的模型：按剧本回答，用来在没有 API key 的情况下验证循环是否正常。"""

    def __init__(self, script):
        self.script = list(script)

    def __call__(self, messages, tools):
        return self.script.pop(0) if self.script else ("（剧本演完了）", [])


def selftest():
    script = [
        ("我需要先算一下。", [{"id": "1", "name": "calculator", "args": {"expression": "(128*37+15)/7"}}]),
        ("再存成笔记。", [{"id": "2", "name": "save_note",
                          "args": {"title": "计算结果", "content": "结果是 678.7142857142857"}}]),
        ("算好了：(128*37+15)/7 = 678.71，已经存进笔记。", []),
    ]
    print("=== 离线自测：不调用 API ===")
    answer, messages = run("算一下 (128*37+15)/7 并存成笔记", model=FakeModel(script))
    print("回答：", answer)
    checks = [("循环执行了工具", any(m.get("role") == "tool" for m in messages)),
              ("工具结果进入对话", any("678.71" in str(m.get("content")) for m in messages)),
              ("草稿文件已生成", (NOTES_DIR / "计算结果.md").exists()),
              ("最终给出结论", "678.71" in answer)]
    for name, ok in checks:
        print(("  ✓ " if ok else "  ✗ ") + name)
    return 0 if all(ok for _, ok in checks) else 1


# ------------------------------------------------------------------ 命令行
def main():
    parser = argparse.ArgumentParser(description="最小可用 Agent 实验")
    parser.add_argument("-q", "--ask", help="问一个问题后退出")
    parser.add_argument("--selftest", action="store_true", help="离线自测，不调用 API")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    if not config.has_api_key():
        print(config.hint(), file=sys.stderr)
        return 2

    try:
        import openai  # noqa: F401
    except ImportError:
        print("缺少 openai 库。请用同目录的 ./run.sh 启动，或手动执行：\n"
              '  python3 -m venv .venv && .venv/bin/pip install "openai>=1.0"', file=sys.stderr)
        return 2

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    try:
        if args.ask:
            answer, _ = run(args.ask, messages)
            print("\n" + answer)
            return 0

        print("Agent 已就绪（模型 %s，密钥 %s）。输入 /exit 退出，/reset 清空对话。\n"
              % (config.MODEL, config.masked_key()))
        while True:
            try:
                line = input("你 > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            if line in ("/exit", "/quit"):
                return 0
            if line == "/reset":
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                print("对话已清空。\n")
                continue
            try:
                answer, messages = run(line, messages)
            except Exception as exc:
                print("  调用失败：%s" % exc)
                continue
            print("\nAgent > %s\n" % answer)
    except KeyboardInterrupt:
        print("\n已退出。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
