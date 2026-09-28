# 最小可用 Agent 实验

一个文件、四种工具、一个循环。跑起来就能看见 Agent 到底在做什么。

## 跑起来

环境已经装好（同目录 `.venv/`，Python 3.9 + openai 2.48.0），直接运行即可：

```bash
./run.sh --selftest        # 离线自测，不调用 API
./run.sh                   # 交互模式
./run.sh -q "现在几点？算一下 (128*37+15)/7，存成笔记"   # 单次提问
```

依赖只有 `openai>=1.0` 一个（见 `requirements.txt`）。换电脑或删了 `.venv` 后，
`./run.sh` 会自动重建虚拟环境并安装；也可以手动：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

注意：直接用 `python3 agent.py` 会报缺少 openai 库——因为系统 Python 里没装，
本实验用的是自带的 `.venv`。所以请走 `./run.sh`，或者写 `.venv/bin/python agent.py`。

## 它到底在做什么

模型没有记忆、也不能执行代码。它只会输出"我要调用 calculator，参数是 X"。
真正干活的是 `agent.py` 里的循环：

```
你的问题 → 问模型 ─┬─ 它要工具 → 你执行 → 结果塞回对话 → 再问模型
                   └─ 它不要工具 → 它的文字就是答案
```

四种工具：`calculator` 计算、`get_time` 看时间、`save_note` 存笔记、`list_notes` 列笔记。
笔记存在同目录的 `notes/` 里。

## 几个可以动手改的地方

- **加工具**：写一个普通函数，再加一段 JSON Schema 到 `TOOLS_SCHEMA`，最后登记进 `TOOLS_IMPL`。循环代码不用动。
- **换模型**：改 `BASE_URL` 和 `MODEL` 即可，任何 OpenAI 兼容接口都能用。
- **控制成本**：`MAX_STEPS` 是单个问题的最大循环步数，调小可以防止它反复调工具烧钱。
- **看原理**：读 `run()` 函数，一共二十来行，这就是 Agent 的全部。

## 配置（密钥不写在代码里）

```
.env            真实密钥存这里（权限 600，已被 .gitignore 排除，不要外传）
.env.example    模板，可安全分享；复制成 .env 再填自己的 key
config.py       读取配置：环境变量 > .env 文件 > 默认值
agent.py        只 import config 取用，文件内不含任何密钥
```

换 key 只改 `.env` 一行，不用碰代码：

```bash
# .env
DEEPSEEK_API_KEY=sk-你的新key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

也可以临时用环境变量覆盖（优先级更高，不落磁盘）：

```bash
export DEEPSEEK_API_KEY=sk-xxxx
./run.sh -q "你好"
```

密钥没配置时，程序会直接给出上面这段提示并退出，不会抛异常。
启动时会打印掩码后的密钥（形如 `sk-ab12****cd34`），方便你确认用的是哪一把。

**安全提醒**：`.env` 里的 key 一旦外泄（发群、截图、提交到 git）就等于公开，
建议去控制台轮换一次。`.gitignore` 已经挡住了 `.env`、`.venv/`、`notes/`、`__pycache__/`。
