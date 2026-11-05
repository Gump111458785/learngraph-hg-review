# 冯甘雨：V3 H/G 验收与成员交接

本记录对应 `docs/TEAM_TASKS.md` 的成员 2 要求。程序验收、真实模型审核、人工复核和接收方签收分别记录；未签收项保持 pending。

## 本次补齐的实现

- `learngraph_review/quiz.py`：专门审核练习题干、参考答案、评分规则。三个组件必须各有一次结论；通过项必须能定位到教案或原文。遗漏组件、虚构引句、重复来源、无法定位依据、目标被替换均不能通过。
- `learngraph_review/team_adapter.run_quiz_live`：校验课节、题目、知识点、当前会话来源编号及 locator，保存完整分项报告。
- `agents.learning_services.audit_practice`：将分项结果转换成既有 `AuditDecision/RepairIssue`；不确定转人工，明确问题归 content。未通过的题目不交付，已交付教案保留。
- G 返修诊断复用 H/G 的模型、预算与用量记录，不再额外要求配置 `LLM_MODEL`；诊断包含本会话原文和 G 结果。evidence/graph/plan/content/uncertain 的分类供主图验证和路由。
- G 接入保留 V3 显式 `sources` 参数，也兼容旧文件 registry；默认相对路径按消费方项目根目录解析。

公共合同及其字段未扩展。完整题目报告存在 `AuditDecision.report_path` 指向的本地 JSON 中，分别列出三个组件的结论、理由、修改意见、正文与依据位置及用量。诊断报告另含 `audit_report_path` 指向底层 G 报告。

## 一次复现

在团队工程根目录、激活已安装 requirements 与 requirements-web 的环境后运行：

```bash
python -m tools.validate_hg --mode offline --out outputs/hg-acceptance-new
python -m pytest -q
```

`offline` 强制注入明确标记的模型替身，不读取个人 Key；预期输出 `all_expected=True`。输出已存在时拒绝覆盖。固定输入位于 `examples/hg_v3/cases.json`，参考产物位于 `examples/hg_v3/expected_offline/`，其中 `<RUN_DIR>` 是运行目录占位符。不要直接用占位路径调用 A，应使用脚本本次实际生成的文件。

脚本生成混合资料 DOCX，经过真正的解析器和 H 适配层，生成 `FileReviewReport`、块级 H 报告、仅采纳块 `Material`；随后调用 A 的 `approved_uploads` 验证块交接。G 使用同一原文，生成错误稿、修订稿、资料不足及三种练习失败记录。它不调用其他 Agent 的生成能力或外部搜索，不将预置诊断当成模型实测。

## 交给成员 3：H→A

查看 `h-public.json`、`h-to-a.json`、`reports/h-*.json` 与 `evidence.json`。确认：

1. `review_status=partial`，文件级仍为 `unreviewed`。
2. 知识段 b0001 被采纳，广告段 b0002 被排除；ID、段落位置、原文与理由可追溯。
3. A 使用 `approved_sources_path` 中的块，不重读整份含广告的原文件。
4. 原文来源编号与 evidence locator 对应。

## 交给成员 1、6：D↔G 与返修

查看 `lesson_bad.json`、`lesson_good.json`、`uncertain.json` 和其 report_path。错误稿将列表/元组可变性颠倒；修订稿恢复与原文一致的陈述。核对原文和具体段落，再检查 `AuditDecision.issues` 的类别、理由、依据、knowledge_ids、queries。`missing_lesson_sources.json` 是模型调用前返回的 evidence 问题单，包含知识点和补证查询；无法确定原因归 uncertain，不能默认交给 D。

`tests/hg/test_quiz_review.py` 检查五类诊断的结构与用量记录；`tests/test_learning_v3.py` 验证分类路由、复审与预算。二者验证程序行为，不证明真实模型会正确归因。原因不确定例中没有性能实验，不能把“使用元组一律提高十倍速度”判为事实正确。

## 交给成员 1：练习审核

分别查看 `quiz_good.json` 和 `quiz_bad_prompt.json`、`quiz_bad_reference_answer.json`、`quiz_bad_rubric.json`，再打开详细报告中的 checks：

| 部分 | 注入错误 | 应核对的依据 |
|---|---|---|
| 题干 | 预设列表与元组都不可变 | 教案目标与原文关于列表可变的陈述 |
| 参考答案 | 元组可变而列表不可变 | 原文与教案的可变性定义 |
| 评分规则 | 正确答案零分，错误答案满分 | 题干条件、正确参考答案与评分点 |

题目未通过时，主图 `status=blocked`，未审核题干不进入公开交付；原教案仍保留。来源缺失例必须在模型调用之前阻止通过。JSON 内包含参考答案，属于内部验收材料，不能在学习者作答前公开。

## 真实 API 与人工复核

真实运行命令如下，会使用本机 Key 并产生少量付费调用：

```bash
python -m tools.validate_hg --mode live --out outputs/hg-acceptance-live-new
```

输入限定为自编、可共享的 Python 基础教学样例，不上传个人文件。完整运行通常包含 1 次 H、3 次 G 教案、最多 2 次失败诊断和 4 次练习审核；单次输出最多由 `OPENAI_MAX_OUTPUT_TOKENS` 限定（默认 6000），SDK 保留最多一次传输重试。不能将估算当成账单。原文缺失例在发出请求前阻止，不产生该例的模型调用。

2026-11-05：真实调用被自动审批拒绝，原因是此前约定暂缓付费联调；需要用户针对本批样例外发及费用明确授权后才能执行。当前没有新真实审核结果，不填写虚构的模型响应或人工签名。

人工复核者用同一输出目录填写 `docs/HG_V3_SIGNOFF.md`；应写姓名、版本、样例 ID、打开的引用位置、同意/质疑理由和实际运行结论。机器和 AI 辅助检查均不能代签。

## 课堂汇报

个人模块页覆盖 H 混合资料、G 错误稿→修订稿、练习三组件失败、返修路由和验收边界；当前标明“离线预置案例”。[六页可编辑汇报文件](hg-v3/冯甘雨-HG-V3-离线验收汇报.pptx) 已逐页渲染检查。真实审核获准完成后，补充真实输入输出截图、模型与耗时，更新最后一页的验收状态。

## 独立包调用练习审核

独立包不需要团队 core 即可导入 `QuizDraft` 和 `review_quiz`。输入为内部 Context、QuizDraft、教案 TextBlock 数组和来源 Material 数组：

```python
from learngraph_review import ReviewService
from learngraph_review.quiz import QuizDraft, review_quiz
# context、lesson_blocks、sources 均是内部丰富模型；不要直接传团队公共 LessonDraft。
report = review_quiz(ReviewService(), context, quiz, lesson_blocks, sources)
```

上述 ReviewService 默认真实调用 API。独立离线测试使用明确注入的 FixtureGateway；运行 `python -m pytest -q` 不需要密钥。完整团队脚本请把 `integration/learngraph/tools/validate_hg.py` 放入团队 tools 后，在团队根目录运行；它依赖 V3 公共合同和服务。
