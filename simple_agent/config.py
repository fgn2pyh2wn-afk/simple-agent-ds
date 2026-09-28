# -*- coding: utf-8 -*-
"""配置读取：API Key 只从这里和 .env 文件来，不写在业务代码里。

读取优先级：环境变量 > 同目录 .env 文件 > 默认值
（环境变量优先方便临时覆盖，也方便 CI 里注入，不落到磁盘。）
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def load_env_file(path=None):
    """解析 .env：# 开头是注释，支持 KEY=VALUE 和带引号的值。"""
    path = Path(path) if path else ENV_FILE
    data = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        data[name.strip()] = value.strip().strip('"').strip("'")
    return data


_FILE_ENV = load_env_file()

API_KEY = os.environ.get("DEEPSEEK_API_KEY") or _FILE_ENV.get("DEEPSEEK_API_KEY", "")
BASE_URL = (os.environ.get("DEEPSEEK_BASE_URL") or _FILE_ENV.get("DEEPSEEK_BASE_URL")
            or DEFAULT_BASE_URL)
MODEL = os.environ.get("DEEPSEEK_MODEL") or _FILE_ENV.get("DEEPSEEK_MODEL") or DEFAULT_MODEL


def has_api_key():
    """Key 是否存在且看起来合法。"""
    return bool(API_KEY) and API_KEY.startswith("sk-") and "在这里填" not in API_KEY


def masked_key():
    """打日志/启动提示用，永远不要把完整 Key 打出来。"""
    if not has_api_key():
        return "（未配置）"
    return "%s****%s" % (API_KEY[:7], API_KEY[-4:]) if len(API_KEY) > 14 else "（已配置）"


def hint():
    """没配置时给用户的提示。"""
    return ("没有找到 API Key。请任选一种方式：\n"
            "  1) 编辑 %s，把 DEEPSEEK_API_KEY 填成你的 key\n"
            "  2) 或设置环境变量：export DEEPSEEK_API_KEY=sk-xxxx\n"
            "（如果还没有 key，去 https://platform.deepseek.com 申请）" % ENV_FILE.name)
