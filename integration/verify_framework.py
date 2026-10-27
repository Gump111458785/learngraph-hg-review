"""Test this H/G source against a local team checkout using an isolated copy.

Run with the team's Python environment. Never modifies the supplied checkout,
loads its .env, fetches private code, or makes paid model calls itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _ignore_private(directory: str, names: list[str]) -> list[str]:
    excluded = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "outputs",
        "uploads",
        "logs",
        "runtime",
        "audit-logs",
        ".streamlit",
        ".aws",
        ".ssh",
    }
    return [
        name
        for name in names
        if name in excluded
        or (name.startswith(".env") and name != ".env.example")
        or name.endswith(
            (
                ".sqlite",
                ".sqlite-shm",
                ".sqlite-wal",
                ".sqlite3",
                ".db",
                ".pyc",
                ".pem",
                ".key",
                ".log",
            )
        )
    ]


def prepare(framework: Path, out: Path) -> Path:
    framework, out = framework.resolve(), out.resolve()
    if not (framework / "core/contracts.py").is_file():
        raise ValueError("未找到团队 core/contracts.py")
    if out.is_relative_to(framework):
        raise ValueError("输出目录必须在团队工程外，避免递归复制或改动原始工程")
    candidates = [
        relative
        for relative in (Path("learngraph_review"), Path("src/learngraph_review"))
        if (framework / relative).is_dir()
    ]
    if len(candidates) != 1:
        raise ValueError("必须存在且仅存在一份 H/G 包，避免根目录与 src 副本互相遮蔽")
    if out.exists():
        raise ValueError("输出目录已存在；请指定新目录，原记录不会覆盖")
    out.mkdir(parents=True)
    target = out / "framework"
    shutil.copytree(framework, target, ignore=_ignore_private)
    package = target / candidates[0]
    source = Path(__file__).resolve().parents[1] / "src/learngraph_review"
    hashes = {}
    # Preserve the team's NOTICE; replace only our Python runtime files.
    for old in package.glob("*.py"):
        old.unlink()
    for module in source.glob("*.py"):
        shutil.copy2(module, package / module.name)
        hashes[module.name] = hashlib.sha256(module.read_bytes()).hexdigest()
    (out / "source-manifest.json").write_text(
        json.dumps(
            {
                "source": str(source),
                "framework": str(framework),
                "target_layout": str(candidates[0]),
                "sha256": hashes,
                "api_calls": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--python", default=sys.executable, help="已安装团队 requirements 的 Python；默认当前解释器"
    )
    args = parser.parse_args(argv)
    interpreter = shutil.which(os.path.expanduser(args.python))
    if not interpreter:
        parser.error("指定的 Python 解释器不存在或不可执行")
    try:
        target = prepare(args.framework, args.out)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    out = args.out.resolve()
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("PYTHONPATH", None)
    env.pop("HG_PROJECT_ROOT", None)
    env.update(
        PYTHON_DOTENV_DISABLED="1",
        HG_REVIEW_MODE="mock",
        HG_SOURCES_FILE="",
        HG_REVIEW_OUTPUT_DIR=str(out / "reports"),
    )
    with (out / "pytest.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [interpreter, "-m", "pytest", "-q", f"--junitxml={out / 'junit.xml'}"],
            cwd=target,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    print((out / "pytest.log").read_text(encoding="utf-8"))
    print(f"Framework checkout unchanged; results: {out}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
