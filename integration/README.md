# 团队工程接入与复验

本目录保存冯甘雨负责的公共入口、工厂增补片段、接入测试和隔离验证脚本。它依赖团队工程的公共设施，不能作为完整应用启动。已验证基线：2026-10-27 R1，团队提交 `d129c60`；个人包 0.2.0。

## 当前 R1 的使用方式

团队已经纳入根目录单份 `learngraph_review/`、公共入口和 `core.llm.get_review_service()`。在团队根目录安装团队自己的 `requirements.txt`，无需再安装个人仓库的 editable 包。个人仓库继续使用 `src/` 布局；同步时不要在团队增加另一份 `src/learngraph_review/`，也不要覆盖组长的 pyproject、State、路由或其他 Agent。

团队固定 `openai==3.37.0`，个人库依赖现为 `>=2,<4`，个人 requirements 同样固定 3.37.0。公共签名和文件级状态保持兼容；R1 的 `review_status`、`report_path`、`approved_sources_path` 可供主图和界面直接读取。

## 隔离验证后续框架

先安装团队自己的依赖。在个人仓库根目录运行，路径替换为本机实际目录：

```bash
python integration/verify_framework.py --framework /path/to/learngraph-multiagent --python /path/to/learngraph-multiagent/.venv/bin/python --out outputs/framework-check
```

Windows 的解释器通常为 `.venv/Scripts/python.exe`，含空格的路径请加引号。`--python` 必须是已经安装团队依赖的解释器；默认使用当前 Python。

脚本只在新输出目录创建工程副本，按目标现有 root/src 布局替换本人的 Python 运行文件，保留团队 `NOTICE.md`；不修改输入工程。复制排除 `.env`、虚拟环境、上传、输出和运行数据库，测试子进程去除 API Key、禁用 dotenv 并强制 Mock。已有输出会拒绝覆盖。输出目录必须在团队工程之外。

结果包括 `pytest.log`、`junit.xml`、`source-manifest.json`。退出码来自团队 pytest；只有全量通过才可视为当前离线兼容。2026-10-27 的 R1 验证结果为 120 项通过。

## 初次移植或审核同步差异

1. 把个人 `src/learngraph_review/*.py` 对应同步到团队现有包目录，保留其 `NOTICE.md`，不要建立第二份包。
2. `learngraph/agents/h_file_review.py`、`learngraph/agents/g_lesson_audit.py`、`learngraph/tools/file_extractors.py` 是本人的公共入口参考。R1 已有这些入口，应逐项比较，不直接覆盖组长新增逻辑。
3. `learngraph/core_llm_addition.py` 只提供 `get_review_service()` 工厂参考。R1 已接入，勿重复添加，也勿覆盖原 `get_chat_model()`。
4. 公共接入测试现在位于 `learngraph/tests/hg/`，可放入团队 `tests/hg/`；包含独立 fixture 和 conftest，保留团队顶层禁止网络的 fixture。测试包含采纳、部分采纳、报告路径、缺失文件和原文约束。
5. 在团队根目录运行 `python -m pytest -q`。需要发布的同步应走团队现有审阅流程。

## 真实模式交接

本机设置 Key、`HG_REVIEW_MODE=live`、G 所需 `HG_SOURCES_FILE`。先核对 source_id 和 locator，再执行会付费的调用。默认相对 registry/输出路径基于团队项目根目录；可用 `HG_PROJECT_ROOT` 明确指定根目录。保存失败会抛出 `ReviewError`，不会交付无记录的通过结果。

R1 已保存上传字节，但 A 尚未消费 H 的仅采纳块 JSON，主图会明确阻塞；G 的真实来源原文也需要 A/联调者提供。本次没有代替其他成员完成这些功能，也没有执行真实付费 API 联调。公共协议与内部丰富模型的区别见 [任务 2 文档](../docs/task2-hg.md) 和 [对齐记录](../docs/FRAMEWORK_ALIGNMENT.md)。
