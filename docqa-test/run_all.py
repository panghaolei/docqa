"""PyCharm 一键运行入口。

用法（在 PyCharm 中直接右键 Run，或命令行执行）：

    python run_all.py                      # 跑全部（含接口 + RAG，跳过性能与 UI）
    python run_all.py --scope unit         # 只跑单元测试（不需要后端服务）
    python run_all.py --scope api          # 只跑接口测试
    python run_all.py --scope rag          # 只跑 RAG 用例与质量评测
    python run_all.py --scope perf         # 跑性能并发用例
    python run_all.py --scope e2e          # 跑前端 UI 自动化
    python run_all.py --doc-format pdf     # 用 PDF 语料跑（验证 Tika 解析链路）
    python run_all.py --open-report        # 跑完自动用浏览器打开 HTML 报告

PyCharm 配置建议：
    Run/Debug Configurations → Python → Script path 选择本文件，Working directory 选 docqa-test。
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "reports" / "report.html"


def _ensure_utf8_stdio() -> None:
    """Windows 控制台默认 GBK，直接打印中文/符号可能抛 UnicodeEncodeError。

    统一把标准输出重配为 UTF-8，并用 replace 兜底，保证测试结果一定能打印出来。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # pragma: no cover - 老版本解释器或非文本流
            pass

SCOPES = {
    "unit": ["tests/unit"],
    "api": ["tests/api"],
    "rag": ["tests/rag"],
    "perf": ["tests/perf"],
    "e2e": ["tests/e2e"],
    "all": ["tests/unit", "tests/api", "tests/rag"],
}


def build_args(ns: argparse.Namespace) -> list[str]:
    args = SCOPES[ns.scope]
    if ns.scope == "all" and ns.with_perf:
        args.append("tests/perf")

    pytest_args = [*args, "-v", "--tb=short", f"--doc-format={ns.doc_format}"]
    if ns.base_url:
        pytest_args += ["--base-url", ns.base_url]
    if ns.scope == "perf" or ns.with_perf:
        pytest_args.append("--run-perf")
    if ns.scope == "e2e":
        pytest_args.append("--run-e2e")
    if ns.no_judge:
        pytest_args.append("--no-judge")
    if ns.keyword:
        pytest_args += ["-k", ns.keyword]
    return pytest_args


def main() -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="DocQA 自动化测试一键运行入口")
    parser.add_argument("--scope", default="all", choices=list(SCOPES),
                        help="运行范围，默认 all")
    parser.add_argument("--base-url", default=None, help="被测后端地址，默认读配置")
    parser.add_argument("--doc-format", default="txt",
                        choices=["txt", "md", "html", "docx", "pdf"],
                        help="知识库语料格式")
    parser.add_argument("--keyword", default=None, help="只运行名称匹配的用例（pytest -k）")
    parser.add_argument("--with-perf", action="store_true", help="在 all 范围下追加性能用例")
    parser.add_argument("--no-judge", action="store_true", help="关闭 LLM 判分（省 token）")
    parser.add_argument("--open-report", action="store_true", help="结束后打开 HTML 报告")
    ns = parser.parse_args()

    import pytest

    print("=" * 78)
    print(f" DocQA 自动化测试 | 范围={ns.scope} | 语料格式={ns.doc_format}")
    print(f" 工作目录: {ROOT}")
    print("=" * 78)

    exit_code = pytest.main(build_args(ns))

    if REPORT.exists():
        print(f"\nHTML 报告：{REPORT}")
        if ns.open_report:
            webbrowser.open(REPORT.as_uri())

    # pytest 退出码：0=全部通过 1=有失败 2=被中断 5=无用例
    mapping = {0: "全部通过", 1: "存在失败用例", 2: "运行被中断", 5: "没有收集到用例"}
    print(f"运行结果：{mapping.get(exit_code, exit_code)}")
    return int(exit_code)


if __name__ == "__main__":
    sys.exit(main())
