# LearnGraph H/G 输入与输出审查

负责的课程合作项目 **任务 2**：H 上传资料相关性与可采纳性审查、G 教学内容与来源核查，以及文件解析、引用定位和修订记录。

这是冯甘雨的个人 H/G 模块仓库，当前版本 **0.2.0**，已对齐 2026-10-27 团队 R1 框架（`d129c60`）。可独立安装、测试和运行命令行；接入团队主工程的文件集中在 [integration/learngraph/](integration/learngraph/)。团队项目：[TheTry16/learngraph-multiagent](https://github.com/TheTry16/learngraph-multiagent)（按团队仓库权限访问）。

## 做了什么

| 能力 | 实现 |
|---|---|
| H 资料审查 | 根据主题、目标逐块判断采纳、拒绝或待复核；只将采纳块导出给 A，保留原文定位 |
| G 内容核查 | 程序校验来源编号与逐字引句，再由模型检查来源支持、目标对应、明显错误和已提供媒体文本的一致性 |
| 文件解析 | 支持 UTF-8/UTF-16 TXT/MD、PDF 文本层、DOCX 正文/表格、PPTX 文本框/表格，保留块及页/段/幻灯片位置 |
| 修订与交付检查 | 内部丰富模型支持版本递增、两轮问题变化对比，以及稿件、目标、资料的哈希绑定 |
| 模型调用 | 直接使用官方 OpenAI Responses API 与结构化输出，默认 `gpt-5-nano`，记录用量与耗时；失败不放行 |
| 验收 | 无 Key 的离线测试、含错/修订样例和预置演示；预置输出不代表真实模型测试结果 |

## 文件说明

| 文件 | 用途 |
|---|---|
| [src/learngraph_review/agents.py](src/learngraph_review/agents.py) | H/G 审查、资料过滤、引用检查、修订与交付检查 |
| [models.py](src/learngraph_review/models.py)、[locations.py](src/learngraph_review/locations.py) | 内部 Pydantic 模型与逐字引句定位 |
| [extract.py](src/learngraph_review/extract.py) | 文件解析 |
| [gateway.py](src/learngraph_review/gateway.py)、[prompts.py](src/learngraph_review/prompts.py) | API、预算/超时、用量及审查提示词 |
| [team_adapter.py](src/learngraph_review/team_adapter.py)、[nodes.py](src/learngraph_review/nodes.py) | 团队公共模型适配与可选节点工厂 |
| [cli.py](src/learngraph_review/cli.py) | `extract/h/handoff/g/schemas` 命令行 |
| [tests/](tests/) | 独立模块测试与离线 fixture，不依赖团队的 A/B/C/D/E/F 或 core |
| [examples/](examples/) | 主题、资料、来源、错误稿、修订稿与离线演示；`expected_offline/` 保存预置记录 |
| [integration/verify_framework.py](integration/verify_framework.py) | 将本模块放入团队工程副本，执行全量离线测试并保存日志、JUnit 和源码哈希 |
| [integration/learngraph/](integration/learngraph/) | 冯甘雨负责的两个公共 Agent 入口、文件解析入口、core 工厂增补片段及公共接入测试，供复制到团队主工程 |
| [docs/task2-hg.md](docs/task2-hg.md) | 详细协议、定位方式、文件限制和联调约定；其中 core/agents 等路径指团队主工程 |
| [pyproject.toml](pyproject.toml)、[.env.example](.env.example) | 安装依赖、模型/超时配置模板 |

## 安装与离线验证

建议使用团队约定的 Python 3.13，在已激活的独立环境中执行：

```bash
python -m pip install -r requirements.txt
python -m pytest -q
python examples/offline_demo.py --out outputs/offline-demo
python -m learngraph_review schemas --out outputs/schemas.json
python -m learngraph_review extract examples/upload_note.txt --id python-types --out outputs/extracted-material.json
```

离线演示预期：`H=partial` → `G1=revise` → `G2=pass`。第一步排除广告块；错误稿将列表/元组可变性写反，随后使用修订稿重新检查。

演示结论由 `OfflineFixtureGateway` 预置，不发送 API 请求。它验证格式、过滤、引用位置和路由，不证明真实模型判断准确。本独立仓库在 Python 3.13、OpenAI SDK **2.54.0 / 3.37.0** 下分别通过 **72 项测试**；将新版模块放入团队 R1 框架副本后通过 **120 项全量测试**。安装文件默认固定团队的 `openai==3.37.0`，库依赖允许 `>=2,<4`。这些结果验证离线协议和程序行为，未执行真实付费调用。完整基线、变更与复现步骤见 [框架对齐记录](docs/FRAMEWORK_ALIGNMENT.md)。

## 真实 OpenAI API 使用

首次将 `.env.example` 复制为 `.env`，已有配置勿覆盖。在本机填写 `OPENAI_API_KEY`，不要提交或发到聊天。
默认 H/G 为 `gpt-5-nano`、推理强度 `minimal`；可分别修改 `OPENAI_MODEL_H`、`OPENAI_MODEL_G`，换模型时应同时确认其支持的推理参数。

**下面的 `h/g` 命令会真实调用 API**；独立 CLI 不受 `HG_REVIEW_MODE=mock` 控制。

```bash
python -m learngraph_review h --context examples/context.json --material examples/material.json --out outputs/h-live.json
python -m learngraph_review handoff --context examples/context.json --material examples/material.json --report outputs/h-live.json --out outputs/h-to-a.json
python -m learngraph_review g --context examples/context.json --lesson examples/lesson_bad.json --sources examples/sources.json --out outputs/g-live-v1.json
python -m learngraph_review g --context examples/context.json --lesson examples/lesson_fixed.json --sources examples/sources.json --previous outputs/g-live-v1.json --out outputs/g-live-v2.json
```

`handoff` 不调用 API。退出码 0=通过/正常导出，2=部分采纳/需修订/待复核/拒绝，1=未完成或输入错误。
业务结果为 2 时仍会保存审查 JSON，不要使用 `&&` 将修订步骤串起来。已有输出会拒绝覆盖，重复运行请改文件名。

报告中查看 `status`、`findings`、正文/证据位置、`revision_record` 与 `usage`。含错稿应指出具体问题，修订稿应重新审核；API 结论仍需要人工抽查。

## 团队主工程接入

团队 R1 已内置本模块，直接在**团队工程根目录**安装它自己的 `requirements.txt` 即可。个人仓库保留 `src/learngraph_review/`，团队使用根目录 `learngraph_review/`；各工程只保留一份运行包，避免两个可编辑安装相互遮蔽。后续同步和验证见 [integration/README.md](integration/README.md)。公共签名保持：

```python
run_h(request: LearningRequest) -> list[FileReviewReport]
run_g(draft: LessonDraft, evidence: list[EvidenceItem]) -> LessonAudit
```

R1 公共报告已支持 `review_status`、`report_path`，H 还返回 `approved_sources_path`。H 部分采纳时仍保留文件级 `unreviewed`，只把采纳块写入交接 JSON；G 的 `needs_review` 可由主图立即阻塞。公共 G `issues` 不再自动拼接逐字正文和本地文件路径，完整定位保存在详细报告。适配层也兼容缺少这些可选字段的旧公共合同。

团队入口默认 `HG_REVIEW_MODE=mock`，改为 `live` 才调用真实 API。G 还需配置 `HG_SOURCES_FILE`，提供与 A 的 source_id/locator 对应的**实际原文 Material 数组**，不能把 A 的 claim 摘要当原文。详细记录默认写入 `outputs/hg/`。相对路径以团队项目根目录为基准；非标准嵌入方式可设置 `HG_PROJECT_ROOT` 为绝对项目目录。

公共 D 目前只提供来源 ID，公共 G 的定位因此对应合并提取文本；精确引句/页段定位、严格版本绑定仍通过内部丰富模型使用。团队主图负责历史交付保护，不能宣称它已自动使用所有内部能力。

本仓库不包含其他成员 Agent 或团队的 core、SQLite、Streamlit 主工程；适配文件与公共接入测试须在已有团队工程中运行。独立 CLI 和 `tests/` 可直接运行。

## 已知范围

真实付费 API 联调尚未执行；目前的验证依据为离线测试和预置演示。团队 R1 已保存真实上传字节并提供隔离和大小检查；H→A 的采纳块接入、G 的真实来源注册表与完整真实闭环仍待对应成员联调。当前主图会在 H→A 未接通处明确阻塞。

不执行 OCR，不直接检查图片/音视频二进制内容；H 采纳表示候选资料准入，不代表已验证网站身份或全部事实。个人仓库未包含 API Key、个人上传文件、运行数据库或其他成员的实现代码。
