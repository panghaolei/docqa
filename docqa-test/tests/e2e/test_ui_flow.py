"""前端 UI 端到端测试（Playwright + Chromium）。

覆盖用户真实操作路径：
    登录 → 新建对话 → 上传文档 → 等待解析完成 → 提问 → 看到流式回答与引用来源

为什么在已有接口测试的情况下还要做 E2E？
    接口测试验证"后端能力"，E2E 验证"用户能不能用上"。
    例如 SSE 流式解析（前端 fetch + ReadableStream）、marked + DOMPurify 渲染、
    文档状态轮询等，这些只有在真实浏览器里跑才能覆盖，
    也是"前后端联调闭环"的最终验收标准。

运行前准备：
    pip install playwright && playwright install chromium
    npm run dev                 # 启动前端 http://localhost:5173
    pytest tests/e2e --run-e2e
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import requests

from conf.settings import PROJECT_ROOT
from core.logger import get_logger
from utils import doc_factory

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(300)]

log = get_logger("e2e")

SHOT_DIR = PROJECT_ROOT / "reports" / "e2e"


# ===================================================================== #
# 夹具
# ===================================================================== #
@pytest.fixture(scope="module")
def front_url(settings) -> str:
    return settings.get("server.front_url", "http://localhost:5173").rstrip("/")


@pytest.fixture(scope="module")
def page(front_url):
    """启动无头 Chromium 并打开被测前端。"""
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="未安装 Playwright，跳过 UI 自动化（pip install playwright）"
    ).sync_playwright

    try:
        requests.get(front_url, timeout=3)
    except requests.RequestException:
        pytest.skip(f"前端未启动（{front_url}），请先执行 npm run dev")

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900},
                                      locale="zh-CN")
        context.set_default_timeout(30_000)
        pg = context.new_page()
        pg.goto(front_url, wait_until="networkidle")
        yield pg
        browser.close()


@pytest.fixture(scope="module")
def logged_in_page(page, run_id):
    """完成登录，返回已进入主界面的页面对象。"""
    username = f"qa_ui_{run_id}"
    page.fill('input[placeholder="请输入用户名"]', username)
    page.click(".login-btn")
    page.wait_for_selector(".sidebar", timeout=20_000)
    log.info("UI 登录成功：%s", username)
    return page


@pytest.fixture(scope="module")
def kb_file_on_disk(tmp_path_factory) -> Path:
    tmp_dir = tmp_path_factory.mktemp("ui_kb")
    return doc_factory.build(tmp_dir, "txt", "UI自动化知识库.txt", content=doc_factory.KB_TEXT)


# ===================================================================== #
# 用例
# ===================================================================== #
def test_login_page_renders(page):
    """登录页渲染：标题、用户名输入框、进入按钮必须可见。"""
    assert page.locator(".login-card").is_visible(), "登录卡片未渲染"
    assert page.locator('input[placeholder="请输入用户名"]').is_visible(), "缺少用户名输入框"
    assert page.locator(".login-btn").is_visible(), "缺少登录按钮"
    page.screenshot(path=str(SHOT_DIR / "01_login.png"))


def test_login_enters_main_layout(logged_in_page):
    """登录成功：进入主布局，侧边栏、会话区、输入区齐备。"""
    assert logged_in_page.locator(".sidebar").is_visible()
    assert logged_in_page.locator(".topbar-title").is_visible()
    logged_in_page.screenshot(path=str(SHOT_DIR / "02_main.png"))


def test_new_chat_creates_session(logged_in_page):
    """新建对话：侧边栏应出现一条会话记录，且输入区处于可用状态。"""
    before = logged_in_page.locator(".session-item").count()
    logged_in_page.click(".new-chat-btn")
    logged_in_page.wait_for_timeout(800)
    after = logged_in_page.locator(".session-item").count()
    assert after > before, f"新建对话后会话数未增加（{before} → {after}）"


def test_upload_document_and_wait_done(logged_in_page, kb_file_on_disk):
    """上传文档：等待状态变为「已完成」，验证前端轮询与状态渲染逻辑。"""
    logged_in_page.set_input_files(".upload-trigger input[type=file]", str(kb_file_on_disk))
    logged_in_page.wait_for_selector(".doc-item .doc-status:has-text('已完成')",
                                     timeout=120_000)
    doc_name = logged_in_page.locator(".doc-item .doc-name").first.inner_text()
    assert "UI自动化知识库" in doc_name, f"文档未出现在列表中：{doc_name}"
    logged_in_page.screenshot(path=str(SHOT_DIR / "03_uploaded.png"))


def test_ask_question_shows_streaming_answer(logged_in_page):
    """核心链路：提问后应看到流式回答，并显示引用来源。"""
    logged_in_page.fill(".chat-input textarea", "入职满 3 年的员工每年可以享受多少天年假？")
    logged_in_page.click(".send-btn")

    # 等待 AI 气泡出现内容
    logged_in_page.wait_for_function(
        """() => {
            const bubbles = document.querySelectorAll('.msg-row.assistant .msg-bubble');
            const last = bubbles[bubbles.length - 1];
            return last && last.innerText.trim().length > 5;
        }""",
        timeout=120_000,
    )

    answer = logged_in_page.locator(".msg-row.assistant .msg-bubble").last.inner_text()
    log.info("UI 回答：%s", answer[:120].replace("\n", " "))
    assert len(answer.strip()) > 5, f"回答为空：{answer!r}"
    assert any(t in answer for t in ["10 天", "10天", "十天"]), (
        f"UI 展示的回答未包含正确事实：{answer[:200]}"
    )

    # 引用来源标签（前端 meta 事件渲染）
    refs = logged_in_page.locator(".msg-refs").last
    if refs.count() > 0:
        assert "UI自动化知识库" in refs.inner_text(), f"引用来源错误：{refs.inner_text()}"

    logged_in_page.screenshot(path=str(SHOT_DIR / "04_answer.png"), full_page=True)


def test_history_is_restored_after_switch(logged_in_page):
    """历史恢复：切换会话后再切回，消息应能从后端重新加载渲染。"""
    items = logged_in_page.locator(".session-item")
    if items.count() < 2:
        pytest.skip("会话不足以验证切换逻辑")

    items.first.click()
    logged_in_page.wait_for_timeout(500)
    items.nth(1).click()
    logged_in_page.wait_for_timeout(1500)

    bubbles = logged_in_page.locator(".msg-bubble")
    assert bubbles.count() > 0, "切换会话后历史消息丢失"


def test_logout_returns_to_login_page(logged_in_page):
    """退出登录：应清除本地 token 并回到登录页。"""
    logged_in_page.click(".user-action")
    logged_in_page.wait_for_selector(".login-card", timeout=15_000)
    assert logged_in_page.locator(".login-card").is_visible(), "退出后未回到登录页"
    logged_in_page.screenshot(path=str(SHOT_DIR / "05_logout.png"))


def test_streaming_marker_disappears_after_answer(logged_in_page, run_id):
    """状态回归：流式结束后发送按钮必须恢复可用（不能一直停留在「思考中」）。"""
    logged_in_page.fill('input[placeholder="请输入用户名"]', f"qa_ui_{run_id}")
    logged_in_page.click(".login-btn")
    logged_in_page.wait_for_selector(".sidebar", timeout=20_000)

    btn = logged_in_page.locator(".send-btn")
    for _ in range(30):
        if "思考中" not in btn.inner_text():
            break
        time.sleep(0.5)
    assert "思考中" not in btn.inner_text(), "流式状态未复位，按钮卡在思考中"
