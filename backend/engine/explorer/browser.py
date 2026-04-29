import asyncio
from dataclasses import dataclass, field
from playwright.async_api import async_playwright, Page, Browser


@dataclass
class ElementInfo:
    tag: str
    text: str = ""
    selector: str = ""
    aria_label: str = ""
    classes: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)


class BrowserController:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser = None
        self.page: Page = None

    async def start(self):
        self._playwright = await async_playwright().__aenter__()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN"
        )
        self.page = await context.new_page()

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def goto(self, url: str, timeout_ms: int = 30000) -> dict:
        try:
            await self.page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            return {"success": True, "url": self.page.url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    async def wait_for_page_ready(self, strategy: str = "networkidle", timeout_ms: int = 10000) -> bool:
        try:
            if strategy == "networkidle":
                await self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
            elif strategy == "domcontentloaded":
                await self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            else:
                await asyncio.sleep(timeout_ms / 1000)
            return True
        except Exception:
            return False

    async def collect_interactive_elements(self) -> list[ElementInfo]:
        elements = []
        interactive_tags = ["button", "a", "input", "select", "textarea"]
        for tag in interactive_tags:
            locators = self.page.locator(tag)
            count = await locators.count()
            for i in range(min(count, 200)):
                try:
                    el = locators.nth(i)
                    if not await el.is_visible():
                        continue
                    text = await el.inner_text() if tag in ("button", "a") else ""
                    text = text.strip()[:200] if text else ""
                    classes = await el.get_attribute("class") or ""
                    aria = await el.get_attribute("aria-label") or ""
                    selector = self._build_selector(tag, text, aria, classes)
                    elements.append(ElementInfo(
                        tag=tag, text=text, selector=selector,
                        aria_label=aria,
                        classes=classes.split() if classes else [],
                    ))
                except Exception:
                    continue
        return elements

    def _build_selector(self, tag: str, text: str, aria: str, classes: str) -> str:
        if text and len(text) < 50:
            return f"{tag}:has-text('{text}')"
        if aria:
            return f"{tag}[aria-label='{aria}']"
        if classes:
            first_class = classes.split()[0]
            return f"{tag}.{first_class}"
        return tag

    async def take_screenshot(self, path: str):
        await self.page.screenshot(path=path, full_page=False)

    async def get_page_summary(self) -> dict:
        url = self.page.url
        title = await self.page.title()
        dom_text = await self.page.inner_text("body")
        return {"url": url, "title": title, "text_snippet": dom_text[:500]}

    async def dismiss_dialogs(self) -> bool:
        try:
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            close_btns = self.page.locator("button:has-text('关闭'), button:has-text('取消'), .modal-close")
            count = await close_btns.count()
            if count > 0:
                await close_btns.first.click()
            return True
        except Exception:
            return False
