# Mini Coding Agent

Mini Coding Agent 以项目要求和可选历史节点为输入，通过 DeepSeek-V4-flash 多轮对话，在本地工作区构建、测试并改进目标项目。

## 工作流程与特色

Agent 首先把项目要求拆成若干独立功能指标，并为每项指定验证方法；随后对照指标分析需求歧义，记录低、中、高风险假设，高风险问题必须在实现前给出明确结论。遇到重要架构选择时，它提出二至三个候选方案，列出优缺点与评分并选择方案，而非直接采用首次生成的设计。

选定方案后，Agent 浏览已有文件，创建源码、配置、依赖和说明，运行编译或测试命令，再依据真实输出修改项目。成功命令会自动绑定到验收项；失败输出会保存，重复失败时要求更换方法。常规测试全部通过后，还必须设计并执行非法输入、空数据、极端值等边缘或反例测试。若发现程序出错或未达预期效果，Agent 继续改进方案；若修改使项目变差，可返回至未验证检查点。只有验收证据、风险处理、反例测试和入口检查全部通过，才会总结运行方式并输出项目。

所有对话树状保存。可恢复当前分支，或从指定历史节点继续，在保留原方案的同时尝试新方案；其他分支决策仅在可能降低修复成本时读取。历史过长时，旧消息被压缩为带节点来源的结构化摘要，同时保留近期完整工具轮次。

## 安装与运行

```powershell
pip install -r requirements.txt
$env:OPENAI_API_KEY="你的密钥"
python main.py "你训练一个CNN模型用于手写体数字识别" --workspace generated_project
```

也可执行 `python main.py --requirement-file 需求.pdf `。支持 PDF、DOCX、TXT、Markdown。也可直接运行程序，按提示输入要求在默认设置下运行。


## 命令行参数

- `requirement`：直接提供需求；省略时从交互或标准输入读取。
- `--requirement-file PATH`：读取需求文件，与文本需求互斥。
- `--workspace DIR`：输出及会话目录，默认 `generated_project`。
- `--base-url URL`、`--model NAME`：覆盖 API 地址和模型。
- `--max-steps N`：最大循环次数；`--quiet`：关闭终端仪表盘。
- `--resume`：恢复当前分支；`--fork NODE_ID`：从历史节点分叉。
- `--list-branches`：列出分支；`--history`：列出全部节点。
- `--audit`：显示验收审计；`--experiments`：显示方案与策略记录。
- `-h, --help`：显示帮助。以上会话查询参数互斥，并在输出后退出。

## 配置项

环境变量包括：`OPENAI_API_KEY`（密钥）、`OPENAI_BASE_URL`（接口地址）、`OPENAI_MODEL`（模型）、`OPENAI_MAX_RETRIES`（重试次数）、`OPENAI_TIMEOUT`（API 超时）；`AGENT_MAX_STEPS`（循环上限）、`AGENT_COMMAND_TIMEOUT`（命令超时）、`AGENT_MAX_HISTORY_CHARS`（压缩阈值）、`AGENT_CONTEXT_KEEP_RECENT_CHARS`（近期历史保留量）、`AGENT_MAX_TOOL_OUTPUT_CHARS`（工具输出上限）、`AGENT_REQUIREMENT_MAX_CHARS`（需求文本上限）、`AGENT_TERMINAL_VISUALS`（设为 `0` 关闭仪表盘）。命令行中的地址、模型和步数优先。

Github Link: https://github.com/cnzjq1/A-coding-agent-NJU-Software-Institute-