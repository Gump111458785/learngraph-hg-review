> 个人仓库说明：本文中的 `agents/`、`tools/` 和 `core/` 路径指团队主工程。相应接入文件位于本仓库 `integration/learngraph/`，独立运行方式以根 README 为准。

# 任务 2：输入与输出审查（H + G）

本实现以成员分工图中的任务 2 为交付边界，对接组长新增的工程骨架：
补充上传资料进入 A 之前的 H，同时实现 D 之后、E 之前的 G。
不实现 A 的联网检索、D 的教材生成、E/F 的出题评分或组长负责的完整 LangGraph 主流程。

## 2026-10-27 R1 对齐

个人包 0.2.0 已对齐团队 `d129c60`：SDK 依赖放宽到 `>=2,<4`，安装默认固定团队 3.37.0；个人使用 src 布局，团队使用根目录单份包。新增公共状态/报告路径映射、项目根目录路径解析、保存失败阻断，并兼容旧公共合同。独立 72 项测试在 SDK 2.54.0 与 3.37.0 均通过，替换模块的团队副本 120 项通过。复现与接入步骤见 [框架对齐记录](FRAMEWORK_ALIGNMENT.md) 和 [integration/README.md](../integration/README.md)。

## 交付与验收

| 图片中的要求 | 实现与验收依据 |
| --- | --- |
| 解析可提取文本文件 | `extract_file` 支持 UTF-8/UTF-16 TXT/MD、PDF 文本层、DOCX 正文和表格；保留页/段落/块位置 |
| H 判断相关性与可采纳程度 | `ReviewService.review_material` 按块给出采纳、待复核、拒绝；`approved_material` 只交接采纳块 |
| G 核查来源、目标、明显错误 | 引用程序校验 + OpenAI 语义审查；包含错误类别、证据、修改意见、目标覆盖 |
| 引用定位测试 | 测试引句不存在、错来源、错块、重复引句、中文字符、PDF 页码、虚构模型位置 |
| 含错样例及修订记录 | `lesson_bad.json` / `lesson_fixed.json`；`offline_demo.py` 生成两轮 G 记录及变化清单 |
| 与 3（A）、6（D）、1（E）协作 | 本文交接约定、JSON Schema、`nodes.py` 的 LangGraph 节点工厂和交付前检查函数 |

H 的“采纳”表示可作为 A 的候选资料，不表示已经核实网站身份或全部事实。
G 的结论来自给定证据和模型判断，仍需交叉人工抽查。离线验收使用明确标记的预置模型输出，
不构成真实模型准确率或实际付费调用的证据。

## 安装与配置

按团队约定使用 Python 3.13，通过公共 requirements 安装。H/G 的库源码兼容 Python 3.10+，
但合并后的完整主工程以团队的 3.13 环境为准。不提交个人 uv 锁文件。

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

先创建环境时可执行：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

仅在本机 `.env` 填写 `OPENAI_API_KEY`，该文件已加入 `.gitignore`。
独立库本身不自动读取 `.env`；命令行读取当前工作目录 `.env`，也可在子命令前指定 `--env-file`。
Python 集成方可在应用入口执行 `load_dotenv()`，已有环境变量优先。
本模块通过官方 SDK 的 Responses API 调用 OpenAI；公共入口由 `core/llm.py` 的新增工厂创建审查服务，
不改变原 `get_chat_model()`。完整工程依赖仍以组长的 requirements 为准，不部署本地模型。

默认 H/G 均为 `gpt-5-nano`，默认推理强度 `minimal`，每次输出上限 6000 token；
可用 `OPENAI_MODEL_H` / `OPENAI_MODEL_G` 分别替换。
更换模型时应按该模型文档修改 `OPENAI_REASONING_EFFORT`，不支持推理参数的模型会自动省略该参数。
例如 `gpt-5.4-nano` 应将强度改为 `none` 或其支持的其他值，不能继续使用 `minimal`。
未配置 Key 会明确失败，不会用离线规则冒充模型审查。

官方价格参考（2026-10-24，每百万文本 token，美元）：

| 模型 | 普通输入 | 缓存输入 | 输出 |
| --- | ---: | ---: | ---: |
| gpt-5-nano | 0.05 | 0.005 | 0.40 |
| gpt-5.4-nano | 0.20 | 0.02 | 1.25 |

按默认模型，单次 5000 输入 + 1000 输出 token、无缓存的估算为 **$0.00065**。
这是算术示例，不是本项目实测费用；推理 token 计入输出 token，实际费用由服务端用量和账单决定。
运行报告保存实际返回的模型、response id、输入/缓存/输出/推理 token、耗时和参考估价；
未知模型的估价为 null。SDK 最多重试 1 次；报告只包含最终响应用量，不能代表重试过程的总账单。
每个上传资料调用一次 H，每份单节内容稿调用一次 G，不自动调用更贵模型或重复修订。

独立解析器资料最大 20 MiB，公共 tools 入口保留团队原有 10 MiB 限制；PDF 最大 100 页，提取文本最多 160000 字符。
单次 API 请求（含提示词与 JSON）最多 60000 字符，超限会要求拆分，不会静默截断并通过。
PDF 含无文本页会拒绝并要求 OCR 或移除空白页；DOCX 不提取页眉页脚、批注、文本框或图片文字。
文本位置只对应实际提取文本，不宣称与 PDF 视觉坐标或 DOCX 页码一致。
同时支持 PPTX 文本框与表格提取，page 表示幻灯片编号；不提取图片文字、讲者备注或分组内文本。

## 无 Key 离线验收

```bash
python -m pytest -q
python examples/offline_demo.py --out outputs/offline-demo
python -m learngraph_review schemas --out outputs/schemas.json
```

演示中的模型结果全部由 `OfflineFixtureGateway` 预置，控制台与记录均标记为离线样例。
流程应为 H 部分采纳 → 排除广告 → G 发现来源矛盾 → D 提供 revision 2 → G 放行至 E。
演示输出目录和 CLI 输出文件已存在时会拒绝覆盖，应使用新路径。
`examples/expected_offline/` 保存了一次该脚本生成的审查、交接和修订记录，便于直接检查字段。

测试包括官方 SDK + `httpx.MockTransport` 的请求/响应往返，验证结构化输出、用量解析、
拒绝、截断、429 和超时处理。它不向互联网发送请求，也不使用真实 Key。

## 真实 API 联调（配置 Key 后执行）

本次开发按协作者要求先交付离线验收和 PR，尚未执行以下真实付费调用。

```bash
# 本地解析，不调用 API；--id 便于后续 A/D 维持稳定的来源编号。
python -m learngraph_review extract your-material.docx --id my-source --out outputs/material.json

# H 审查；部分采纳、拒绝或待复核时退出码为 2，但仍输出完整审查记录。
python -m learngraph_review h --context examples/context.json --material examples/material.json --out outputs/h-live.json

# H → A：仅交接已采纳文本块，输出 Material 数组。没有采纳块时为 []。
python -m learngraph_review handoff --context examples/context.json --material examples/material.json --report outputs/h-live.json --out outputs/h-to-a-live.json

# 以下使用自编 sources.json 演示 A 的返回格式；实际运行应使用 A 提供的本节资料。
python -m learngraph_review g --context examples/context.json --lesson examples/lesson_bad.json --sources examples/sources.json --out outputs/g-live-v1.json
python -m learngraph_review g --context examples/context.json --lesson examples/lesson_fixed.json --sources examples/sources.json --previous outputs/g-live-v1.json --out outputs/g-live-v2.json
```

不要用 `&&` 把上述命令串起来：审查未通过时退出码 2 是正常业务结果，仍可用于后续修订。
退出码 0=通过/正常导出；2=部分采纳/需修订/待人工复核/拒绝；1=未完成或输入错误。
示例资料是自编样例，不代表外部权威来源；真实模型结论需人工抽查，不保证样例一定被放行。

## 与 A、D、E 的接口约定

### 对接现有公共工程

`agents/h_file_review.run_h(LearningRequest)`、
`agents/g_lesson_audit.run_g(LessonDraft, list[EvidenceItem])` 签名与返回公共模型均保持原样，
不改 `core/contracts.py`、State、主图或其他成员 Agent。下面的独立库模型是模块内部的丰富表示，
不能直接替换公共协议对象。`tools/file_extractors.extract_text_with_locators` 返回内部 Material，
仅供本模块解析和适配使用。

`HG_REVIEW_MODE=mock`（默认）保留原有 Mock 示例；选择 `live` 后调用实际 API，
缺少 Key、原文或实际文件会明确失败，不会退回 Mock 并标成 live。
公共入口由 `core/llm.get_review_service()` 创建真实服务，独立命令行始终按 API 模式执行。
完整细节保存在 `HG_REVIEW_OUTPUT_DIR`（默认 outputs/hg）中，每轮使用新文件。相对输出目录与 `HG_SOURCES_FILE` 基于团队项目根目录；非标准嵌入方式可用 `HG_PROJECT_ROOT` 指定绝对根目录。保存失败抛出 `ReviewError`，由主图阻断。公共合同承载摘要和可选状态/路径元数据。

H 公共报告：全采纳=accepted，全拒绝=excluded；部分采纳和待复核=unreviewed。
原因是 v0.1 的文件级公共协议不能绑定块级准入，不能把含拒绝块的原文件整体交给 A。
R1 在 reason 之外新增 `review_status`、`report_path` 和 `approved_sources_path`，后者指向仅已采纳块的 Material 数组 JSON；A 负责人应读取该文件，不能重新读取含拒绝块的整个原文件。
团队 Streamlit 现已保存真实上传字节，并提供隔离、大小限制和解析预检；但 A 尚未消费采纳块，主图仍在 H→A 待对接处阻塞。

G 公共入口要求 `HG_SOURCES_FILE` 指向 **Material 数组 JSON**，由 A/联调者提供真实提取原文。
其中 Material.id 对应 EvidenceItem.source_id，Material.source 与 EvidenceItem.locator 的 `#` 前缀一致。
不能只把 EvidenceItem.claim 复制为原文。缺少或不匹配时阻断，组长的 ValueError guard 会持久化 blocked。
v0.1 的 D 只有来源 ID，公共适配层因此使用来源级引用，位置对应合并提取文本；
精确引句和 PDF 页/段定位能力通过下面的丰富库接口使用，待上下游协商后再扩展公共合同。
R1 的 G 公共报告也有 `review_status`、`report_path`，`needs_review` 立即阻塞；公共 issues 不自动附带逐字正文和本地报告路径，完整定位在本地 JSON 中。
公共教案目前也没有 revision/delivered 字段，历史交付保护仍由组长主图承担；
本模块的严格版本绑定与修订对比仅对使用内部 LessonDraft/GReport 的调用方生效。

`HG_REVIEW_MODE=live` 不会使其他 Agent 自动变成真实版本，也不代表完整主流程已完成真实联调。

### 模块内部的丰富接口

数据结构均为 Pydantic 模型，JSON 可通过 `model_validate` 导入、`model_dump(mode="json")` 导出。
使用 `schemas` 命令导出全部公开交换格式，具体示例见 `examples/*.json`。

**H → A（成员 3）：** 接收 `Context` 与 `Material`。H 对每个文本块恰好给出一个结论，
结论必须有可定位原文。`approved_material(material, h_report, context)` 核对资料和目标的哈希后，
只返回已采纳块，无采纳块返回 None。A 保留 `Material.id`、块 id、页/段落、source 和原文，
不要只转发 H 的摘要，勿将拒绝/待复核块混入后续证据。
A 的公开检索证据也可以适配为同一 Material 格式；本模块不承担联网抓取或来源身份认证。

**D → G（成员 6）：** `LessonDraft` 含单元 id、revision、delivered、sections 和可选 media。
每段 Citation 含 `source_id`、`source_anchor`（块 id、逐字引句、出现次数）和正文 `claim_quote`。
`sources` 为 A 提供的本节 Material 数组，id 不得重复。原文位置由程序算出，不由模型编造。
G 会先检查 id/引句可定位性，再让模型检查引用是否真正支持主张、目标对应和明显错误。
缺引用导致待人工复核；错误引用即使模型返回无问题，也会强制返回 D。
修改意见中的 target/evidence 均能定位到本次正文/原文；虚构模型位置会使整次审查失败。

**G → D / E（成员 1）：** status=revise、next_agent=D 时按 findings 修订草稿并增加 revision；
status=needs_review、next_agent=human 时先补依据或人工处理；status=pass、next_agent=E 才能继续。
进入 E 或交付前，调用 `require_delivery_approval(lesson, report, context, sources)`，
再次绑定本次稿件、版本、目标和证据，防止审核通过后改稿或换资料。
该绑定是应用级一致性检查，不是针对外部篡改报告的数字签名；主流程应保管可信的审查记录。

**修订与不可变记录：** `review_lesson(..., previous=上轮GReport)` 检查单元/目标相同且 revision 递增，
生成新增、仍存在及本轮未再报告的问题清单。未再报告不等于已证明修复；以本轮完整审核为准。
服务不改写输入内容；CLI 以新文件保存每轮记录。`delivered=true` 不可进入 D/G 草稿修订循环；
已有课程错误须由后续补充单元/追加更正处理。集成方仍需用持久化交付状态确保已交付事实不能被重置。

媒体只检查提交的真实导出文本、识别转录或描述与关联正文的一致性，不直接读取图片/音视频。
报告 `media_scope` 明确说明范围；不能将文本一致性检查宣传为已验证二进制媒体内容。

```python
from dotenv import load_dotenv
from learngraph_review import ReviewService
from learngraph_review.nodes import make_h_node, make_g_node

load_dotenv()
service = ReviewService()
# 组长现有 LangGraph builder 上可注册；此处不创建或接管完整工作流。
builder.add_node("H", make_h_node(service))
builder.add_node("G", make_g_node(service))
# H 读取 state.context/state.uploads，返回 h_reports/approved_uploads。
# G 读取 context/lesson/sources、可选上轮 g_report，返回 g_report/next_agent。
# 主流程自行将 D/human/E 条件路由接到现有节点，设置有限修订次数并持久化状态。
```

API 超时、拒绝、不完整 JSON、超出预算或模型定位无效时会抛出 `ReviewError`，不会给出通过记录。
主流程应捕获错误并停在当前节点，不能默认进入 E。更详细的节点状态字段以 `nodes.py` 为准。

## 官方依据与待验证项

- [GPT-5 nano 模型、能力与价格](https://developers.openai.com/api/docs/models/gpt-5-nano)
- [GPT-5.4 nano 模型与价格](https://developers.openai.com/api/docs/models/gpt-5.4-nano)
- [Responses 结构化输出与 Pydantic](https://developers.openai.com/api/docs/guides/structured-outputs)

待真实联调确认：账号模型访问权限、网络连通性、实际输出完整性、对含错/无错/资料不足样例的判断、
多次运行稳定性、中文定位失败率及实际用量。提示词要求忽略资料中的恶意指令，但离线测试不能证明模型能抵御注入。
本交付不宣称系统全部 Agent 已完成，也不宣称已验证教学效果。
