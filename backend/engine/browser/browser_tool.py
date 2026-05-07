"""BrowserTools — MCP 风格的浏览器工具封装层

提供 snapshot/click/fill/navigate/hover/select/wait/screenshot/expect 等接口。
底层直接操作 Playwright Page 对象，通过 SemanticSnapshot 和 LocatorEngine 定位元素。
"""

import os
from dataclasses import dataclass, field
from backend.engine.browser.semantic_snapshot import (
    SemanticSnapshot, SnapshotElement, take_snapshot,
)
from backend.engine.browser.locator_engine import compile_locator_from_dict


@dataclass
class ToolResult:
    success: bool
    tool: str
    message: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"success": self.success, "tool": self.tool}
        if self.message:
            d["message"] = self.message
        if self.data:
            d["data"] = self.data
        return d


class BrowserTools:
    def __init__(self, page):
        self.page = page
        self._last_snapshot: SemanticSnapshot | None = None

    async def snapshot(self) -> ToolResult:
        """采集页面语义快照"""
        try:
            snap = await take_snapshot(self.page)
            self._last_snapshot = snap
            element_count = len(snap.all_elements())
            return ToolResult(
                success=True,
                tool="snapshot",
                message=f"采集到 {element_count} 个可交互元素，{len(snap.sections)} 个区域",
                data=snap.to_dict(),
            )
        except Exception as e:
            return ToolResult(success=False, tool="snapshot", message=f"快照失败: {e}")

    async def click(self, ref: str = "", locator: dict = None) -> ToolResult:
        """点击元素，带多候选回退和 detached DOM 重试

        优先使用 locator_dict（如 role+name），每次重新编译为新鲜的 Playwright Locator，
        不依赖快照中的 DOM 引用，避免 Vue/React 重渲染导致的 detached 问题。
        """
        last_error = None
        for attempt in range(3):
            if attempt > 0:
                await self.page.wait_for_timeout(1500)
            else:
                await self.page.wait_for_timeout(500)

            # 优先用 locator_dict 编译新鲜 locator（不依赖快照）
            if locator and locator.get("strategy"):
                loc = compile_locator_from_dict(self.page, locator)
                if loc is not None:
                    try:
                        await loc.click(timeout=10000)
                        # 等待网络空闲（SPA 路由跳转需要时间）
                        try:
                            await self.page.wait_for_load_state("networkidle", timeout=10000)
                        except Exception:
                            pass
                        await self.page.wait_for_timeout(1500)
                        return ToolResult(
                            success=True, tool="click",
                            message=f"点击成功: ref={ref}",
                            data={"url": self.page.url, "title": await self.page.title()},
                        )
                    except Exception as e:
                        last_error = e
                        error_str = str(e).lower()
                        if "detached" in error_str or "not attached" in error_str or "intercept" in error_str:
                            try:
                                await self.page.wait_for_load_state("networkidle", timeout=3000)
                            except Exception:
                                pass
                            continue
                        # role+name 失败，回退到快照候选
                        pass

            # 回退：用 ref 从快照查找候选
            candidates = self._get_candidates(ref, None)
            for loc in candidates:
                try:
                    await loc.click(timeout=10000)
                    try:
                        await self.page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    await self.page.wait_for_timeout(1500)
                    return ToolResult(
                        success=True, tool="click",
                        message=f"点击成功: ref={ref}",
                        data={"url": self.page.url, "title": await self.page.title()},
                    )
                except Exception as e:
                    last_error = e
                    continue

        return ToolResult(success=False, tool="click", message=f"点击失败: {last_error}")

    async def fill(self, ref: str = "", value: str = "", locator: dict = None) -> ToolResult:
        """填写输入框，带多候选回退和 detached DOM 重试"""
        candidates = self._get_candidates(ref, locator)
        if not candidates:
            return ToolResult(success=False, tool="fill", message=f"找不到元素: ref={ref}")

        last_error = None
        for attempt in range(5):
            for loc in candidates:
                try:
                    await loc.wait_for(state="attached", timeout=3000)
                    await loc.click(timeout=3000)
                    await loc.fill("")
                    await loc.fill(value)
                    return ToolResult(
                        success=True, tool="fill",
                        message=f"填写成功: ref={ref}, value={value}",
                        data={"value": value},
                    )
                except Exception as e:
                    last_error = e
                    if "detached" in str(e).lower() or "not attached" in str(e).lower():
                        await self.page.wait_for_timeout(1000)
                        break
                    continue
            if "detached" in str(last_error).lower() or "not attached" in str(last_error).lower():
                candidates = self._get_candidates(ref, locator)

        return ToolResult(success=False, tool="fill", message=f"填写失败: {last_error}")

    async def hover(self, ref: str = "", locator: dict = None) -> ToolResult:
        """悬停元素，带多候选回退"""
        candidates = self._get_candidates(ref, locator)
        if not candidates:
            return ToolResult(success=False, tool="hover", message=f"找不到元素: ref={ref}")

        last_error = None
        for loc in candidates:
            try:
                await loc.hover(timeout=3000)
                return ToolResult(success=True, tool="hover", message=f"悬停成功: ref={ref}")
            except Exception as e:
                last_error = e
                continue

        return ToolResult(success=False, tool="hover", message=f"悬停失败: {last_error}")

    async def select_option(self, ref: str = "", value: str = "", locator: dict = None) -> ToolResult:
        """选择下拉框"""
        try:
            el_locator = self._resolve(ref, locator)
            if el_locator is None:
                return ToolResult(success=False, tool="select_option", message=f"找不到元素: ref={ref}")

            await el_locator.select_option(value, timeout=5000)
            return ToolResult(success=True, tool="select_option", message=f"选择成功: ref={ref}, value={value}")
        except Exception as e:
            return ToolResult(success=False, tool="select_option", message=f"选择失败: {e}")

    async def navigate(self, url: str) -> ToolResult:
        """导航到 URL"""
        try:
            await self.page.goto(url, timeout=15000, wait_until="domcontentloaded")
            return ToolResult(
                success=True, tool="navigate",
                message=f"导航成功: {url}",
                data={"url": self.page.url, "title": await self.page.title()},
            )
        except Exception as e:
            return ToolResult(success=False, tool="navigate", message=f"导航失败: {e}")

    async def press_key(self, key: str) -> ToolResult:
        """按键"""
        try:
            await self.page.keyboard.press(key)
            return ToolResult(success=True, tool="press_key", message=f"按键成功: {key}")
        except Exception as e:
            return ToolResult(success=False, tool="press_key", message=f"按键失败: {e}")

    async def wait(self, ms: int = 1000) -> ToolResult:
        """等待"""
        import asyncio
        await asyncio.sleep(ms / 1000)
        return ToolResult(success=True, tool="wait", message=f"等待 {ms}ms")

    async def screenshot(self, path: str = "") -> ToolResult:
        """截图"""
        try:
            if not path:
                path = f"/tmp/screenshot_{id(self)}.png"
            os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
            await self.page.screenshot(path=path, full_page=True)
            return ToolResult(success=True, tool="screenshot", message=f"截图保存: {path}", data={"path": path})
        except Exception as e:
            return ToolResult(success=False, tool="screenshot", message=f"截图失败: {e}")

    async def expect_visible(self, ref: str = "", locator: dict = None, timeout: int = 5000) -> ToolResult:
        """断言元素可见"""
        try:
            el_locator = self._resolve(ref, locator)
            if el_locator is None:
                return ToolResult(success=False, tool="expect_visible", message=f"找不到元素: ref={ref}")

            await el_locator.wait_for(state="visible", timeout=timeout)
            return ToolResult(success=True, tool="expect_visible", message=f"元素可见: ref={ref}")
        except Exception as e:
            return ToolResult(success=False, tool="expect_visible", message=f"元素不可见: {e}")

    async def expect_text(self, text: str, timeout: int = 5000) -> ToolResult:
        """断言页面包含文本"""
        try:
            locator = self.page.get_by_text(text)
            await locator.first.wait_for(state="visible", timeout=timeout)
            return ToolResult(success=True, tool="expect_text", message=f"页面包含文本: {text}")
        except Exception as e:
            return ToolResult(success=False, tool="expect_text", message=f"页面不包含文本: {text}")

    async def expect_url(self, url_pattern: str) -> ToolResult:
        """断言 URL 包含指定字符串"""
        current = self.page.url
        if url_pattern in current:
            return ToolResult(success=True, tool="expect_url", message=f"URL 包含: {url_pattern}")
        return ToolResult(success=False, tool="expect_url", message=f"URL 不匹配: 当前={current}, 期望包含={url_pattern}")

    def get_last_snapshot(self) -> SemanticSnapshot | None:
        return self._last_snapshot

    def _resolve(self, ref: str, locator_dict: dict = None):
        """解析 ref 或 locator_dict 为 Playwright Locator（返回第一个候选）"""
        candidates = self._get_candidates(ref, locator_dict)
        return candidates[0] if candidates else None

    def _get_candidates(self, ref: str, locator_dict: dict = None) -> list:
        """获取所有候选 Playwright Locator，按优先级排序"""
        result = []

        # 优先用 locator_dict（AI 直接提供）
        if locator_dict:
            loc = compile_locator_from_dict(self.page, locator_dict)
            if loc is not None:
                result.append(loc)

        # 用 ref 从快照查找，收集所有候选
        if ref and self._last_snapshot:
            el = self._last_snapshot.find_element(ref)
            if el and el.locator_candidates:
                for candidate in el.locator_candidates:
                    loc = compile_locator_from_dict(self.page, candidate.to_dict())
                    if loc is not None and loc not in result:
                        result.append(loc)

        return result
