# 冯甘雨：R1 框架对齐记录

验证日期：2026-10-27。个人包版本：0.2.0。团队基线：`TheTry16/learngraph-multiagent@d129c60f95e53d8db2ae670a77134ccf299d171f`，Python 3.13，OpenAI SDK 3.37.0。团队代码按原仓库权限访问；本仓库只发布本人模块和接入文件。

## 对齐结果与变更

旧个人版本覆盖到 R1 后，全量测试为 114 通过、6 失败；失败集中在新增审查状态/报告路径和 `needs_review` 路由所依赖的元数据。旧包的 SDK `<3` 约束也不能满足团队固定的 3.37.0。新版已解决这些兼容问题，保留原 `run_h/run_g` 签名与核心审查逻辑。

| 文件 | 对齐内容 |
|---|---|
| `pyproject.toml`、`requirements.txt` | 版本升为 0.2.0；库允许 OpenAI SDK `>=2,<4`，安装默认固定团队 3.37.0；显式声明测试使用的 httpx 0.28.1，SDK 3 不再间接安装它 |
| `src/learngraph_review/team_adapter.py` | 映射 R1 的 H/G 状态与报告路径；兼容严格旧合同；根据消费方工程定位相对路径，支持 src/root/安装包；保存失败抛出 ReviewError；公共 G issues 不再自动附加逐字正文或报告路径 |
| `.env.example` | 增加可选绝对 `HG_PROJECT_ROOT`，非标准嵌入可明确指定路径基准 |
| `tests/test_adapter_alignment.py` | 13 项回归：新旧合同、部分采纳、G 三种状态、相对路径、保存失败和公共摘要中的逐字引句处理 |
| `integration/verify_framework.py`、`tests/test_framework_verifier.py` | 隔离替换模块并执行团队 pytest；5 项脚本测试覆盖 root/src、隐私文件排除、不可覆盖、重复包和虚拟环境解释器 |
| `integration/learngraph/tests/hg/` | 接入测试移到 R1 使用的 tests/hg 布局，独立提供 fixture；加强状态和报告文件存在检查 |
| `tests/conftest.py`、`.github/workflows/review.yml` | 测试禁用 dotenv/Key；持续检查 SDK 2.54.0 与 3.37.0 |
| `README.md`、`integration/README.md`、`docs/task2-hg.md` | 更新安装、路径、上传现状、公共字段与验证说明 |

团队已经对根目录版本实施等效的 R1 适配。本次个人包加入对多种布局和旧合同的兼容，不要求团队覆盖其现有 core、路由或其他成员 Agent。两边包的目录布局可以不同，不应在同一工程安装两份副本。

## 离线验收

| 检查 | 结果 | 范围 |
|---|---:|---|
| 个人模块 + SDK 2.54.0 | 72 通过 | 原 54 项 + 13 项适配回归 + 5 项隔离验证脚本测试 |
| 个人模块 + SDK 3.37.0 | 72 通过 | 同一组测试，使用团队 SDK |
| 新个人模块覆盖 R1 副本 | 120 通过 | 团队全量测试，含路由、持久化、上传和界面 |
| 加强后的公共入口测试 | 6 通过 | 使用团队真实公共合同与入口，模型为离线 fixture |
| Ruff、依赖一致性 | 通过 | 个人源码/测试/接入文件；安装依赖检查 |

这些测试没有发送真实 OpenAI API 请求，不代表真实模型的判断准确率。旧 SQLite 在新框架中恢复并完成的兼容检查已通过；本次没有更改 State 或数据库格式。

组长原框架的本机全量复验曾有一次界面 AppTest 超过 20 秒（119 通过、1 超时）；该项单独重跑通过，随后完整重跑 120 通过。保留这个现象，不能将一次通过解释为已证明所有机器上的界面时序稳定。

## 复现

个人仓库根目录（独立环境）：

```bash
python -m pip install -r requirements.txt
python -m pytest -q
ruff check src tests examples/offline_demo.py integration
python examples/offline_demo.py --out outputs/offline-demo
python -m learngraph_review schemas --out outputs/schemas.json
```

`requirements.txt` 安装 SDK 3.37.0；验证 SDK 2 时在另一独立环境执行 `python -m pip install -e ".[dev]" "openai==2.54.0"`，随后运行同一组测试。GitHub Actions 自动覆盖这两个 SDK 版本。

使用已安装团队 requirements 的解释器执行全量联调，输出目录须在团队工程之外：

```bash
python integration/verify_framework.py --framework /path/to/learngraph-multiagent --python /path/to/learngraph-multiagent/.venv/bin/python --out outputs/framework-check
```

Windows 将解释器改为 `.venv/Scripts/python.exe`；含空格的路径加引号。输出目录已存在时请换新名字。脚本保留源码哈希、pytest 日志和 JUnit，原团队工程不变，不加载其 `.env`。

## 仍需上下游完成的功能

R1 已保存真实上传字节；A 仍未读取 H 的仅采纳块 JSON，主图在这个交接处明确阻塞。G 真实模式需要 A/联调者提供 `HG_SOURCES_FILE` 原文 Material 数组；不能用 claim 摘要替代。公共 D 只有来源 ID，没有内部模型的逐字引句和 revision/delivered 字段，因此精细引用和严格版本绑定不自动等于主图已接入。

这些属于上下游功能和真实联调范围，并非本次仍未解决的 H/G 离线协议兼容问题。真实付费 API 联调按用户安排另行执行。
