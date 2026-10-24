# 团队工程接入文件

本目录保存冯甘雨负责的公共入口和增补片段。它依赖团队主工程的 `core/contracts.py` 等公共设施，不能将整个目录作为独立应用启动。

1. 先在团队环境中安装本仓库的 H/G 包：`python -m pip install -e /本仓库路径`。
2. 将 `learngraph/agents/h_file_review.py`、`learngraph/agents/g_lesson_audit.py`、`learngraph/tools/file_extractors.py` 对应放入团队工程，保留团队其他模块。
3. 将 `learngraph/core_llm_addition.py` 中的 `get_review_service()` 工厂添加到团队 `core/llm.py`，不要覆盖原 `get_chat_model()`。
4. 将 `learngraph/tests/test_hg_public.py` 放到团队 `tests/`；需要本仓库 `tests/conftest.py` 提供的 fixture，合并其定义时保留团队已有 fixture。
5. 在团队根目录运行 `python -m pytest -q`。离线回归默认 `HG_REVIEW_MODE=mock`。
6. 真实模式配置本机 Key、`HG_REVIEW_MODE=live`、G 所需 `HG_SOURCES_FILE`；先核对源编号与 locator，再做真实调用。

公共合同、State 和主图没有复制到个人仓库，也不由本模块改写。内部丰富模型与公共合同不是同一套格式；完整限制见根 README 与 `docs/task2-hg.md`。
