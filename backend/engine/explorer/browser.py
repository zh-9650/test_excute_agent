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
    # DOM 层级信息
    dom_path: str = ""              # "body > div.app > div.main > form > input"
    parent_tag: str = ""
    parent_classes: list[str] = field(default_factory=list)
    sibling_text: str = ""          # 同级元素文本摘要
    # 元素状态
    is_disabled: bool = False
    is_readonly: bool = False
    href: str = ""                  # <a> 标签
    value: str = ""                 # input/textarea 当前值
    role: str = ""                  # 显式 role 属性
    depth: int = 0                  # DOM 深度


class BrowserController:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Browser = None
        self.page: Page = None
        self.console_logs: list[dict] = []  # 控制台日志捕获

    async def start(self):
        self._playwright = await async_playwright().__aenter__()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--lang=zh-CN",
            ],
        )
        if self.headless:
            context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
        else:
            context = await self._browser.new_context(
                no_viewport=True,
                locale="zh-CN",
            )
        self.page = await context.new_page()
        # 捕获控制台日志（来自 Anthropic webapp-testing / lackeyjb playwright-skill）
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_page_error)

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def goto(self, url: str, timeout_ms: int = 30000, wait_until: str = "domcontentloaded") -> dict:
        try:
            await self.page.goto(url, timeout=timeout_ms, wait_until=wait_until)
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
                    el_type = await el.get_attribute("type") or ""
                    placeholder = await el.get_attribute("placeholder") or ""
                    name = await el.get_attribute("name") or ""
                    title = await el.get_attribute("title") or ""
                    testid = await el.get_attribute("data-testid") or ""

                    # 对于没有文字的按钮/链接，尝试从子元素获取描述
                    if not text and tag in ("button", "a"):
                        text = await self._extract_icon_text(el, classes, aria, title)

                    selector = self._build_selector(tag, text, aria, classes, title=title, testid=testid)
                    elements.append(ElementInfo(
                        tag=tag, text=text, selector=selector,
                        aria_label=aria,
                        classes=classes.split() if classes else [],
                        attributes={"type": el_type, "placeholder": placeholder, "name": name, "title": title, "data-testid": testid},
                    ))
                except Exception:
                    continue

        # 收集带有交互式 ARIA role 的元素（menuitem, link, button, tab, treeitem 等）
        interactive_roles = ["menuitem", "link", "button", "tab", "treeitem", "option", "menuitemradio", "menuitemcheckbox"]
        for role in interactive_roles:
            locators = self.page.locator(f'[role="{role}"]')
            count = await locators.count()
            for i in range(min(count, 100)):
                try:
                    el = locators.nth(i)
                    if not await el.is_visible():
                        continue
                    text = (await el.inner_text()).strip()[:200]
                    aria = await el.get_attribute("aria-label") or ""
                    tag = await el.evaluate("e => e.tagName.toLowerCase()")
                    classes = await el.get_attribute("class") or ""
                    # 构建选择器：优先用 role + text
                    if text and len(text) < 50:
                        selector = f'[role="{role}"]:has-text("{text}")'
                    elif aria:
                        selector = f'[role="{role}"][aria-label="{aria}"]'
                    else:
                        selector = f'[role="{role}"]'
                    elements.append(ElementInfo(
                        tag=tag, text=text, selector=selector,
                        aria_label=aria,
                        classes=classes.split() if classes else [],
                        attributes={"role": role},
                    ))
                except Exception:
                    continue

        # 收集包含文本的可hover元素（文档标题、列表项等）
        # 优先收集数据内容卡片（card类），再收集其他元素
        text_selectors = [
            '[class*="card"]', '[class*="title"]', '[class*="name"]',
            '[class*="row"]', '[class*="record"]', '[class*="entry"]',
            'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5',
        ]
        # 排除的控件类名（搜索框、筛选器、菜单等UI控件）
        # 注意：不排除 header/footer（卡片的 header/footer 是数据的一部分）
        control_keywords = ["search-item", "filter", "menu-item", "tab-", "pagination", "dropdown", "toolbar", "nav-", "sidebar"]
        for sel in text_selectors:
            try:
                locators = self.page.locator(sel)
                count = await locators.count()
                for i in range(min(count, 50)):
                    try:
                        el = locators.nth(i)
                        if not await el.is_visible():
                            continue
                        text = (await el.inner_text()).strip()
                        # 只收集中等长度的文本（太短无意义，太长是容器）
                        if len(text) < 3 or len(text) > 150:
                            continue
                        tag = await el.evaluate("e => e.tagName.toLowerCase()")
                        classes = await el.get_attribute("class") or ""
                        # 排除UI控件元素
                        class_lower = classes.lower()
                        if any(kw in class_lower for kw in control_keywords):
                            continue
                        # 构建选择器（去掉换行符，Playwright不支持）
                        # 对于卡片类元素，用第一个class作为选择器
                        if classes:
                            first_class = classes.split()[0]
                            # 截取文本用于 has-text 匹配，取第一行有意义的文本
                            first_line = text.split('\n')[0].strip()[:40]
                            if first_line:
                                selector = f"{tag}.{first_class}:has-text('{first_line}')"
                            else:
                                selector = f"{tag}.{first_class}"
                        else:
                            clean_text = text[:30].replace('\n', ' ').replace('\r', '')
                            selector = f"{tag}:has-text('{clean_text}')"
                        elements.append(ElementInfo(
                            tag=tag, text=text[:80], selector=selector,
                            aria_label="",
                            classes=classes.split() if classes else [],
                            attributes={},
                        ))
                    except Exception:
                        continue
            except Exception:
                continue

        return elements

    async def collect_dom_hierarchy(self, max_depth: int = 8, max_elements: int = 200) -> list[ElementInfo]:
        """收集带层级关系的 DOM 元素 — 一次 page.evaluate() 完成，性能优于逐元素查询"""
        try:
            elements_data = await self.page.evaluate("""(opts) => {
                const {maxDepth, maxElements} = opts;
                const result = [];
                const interactive = new Set(['A','BUTTON','INPUT','SELECT','TEXTAREA']);
                const interactiveRoles = new Set(['menuitem','link','button','tab','treeitem','option','menubar','checkbox','radio','switch','combobox']);
                const contentTags = new Set(['DIV','LI','TR','TD','TH','SPAN','P','LABEL','H1','H2','H3','H4','H5','A','BUTTON']);

                function walk(el, depth, path) {
                    if (depth > maxDepth || result.length >= maxElements) return;
                    if (!el.tagName) return;

                    const tag = el.tagName.toLowerCase();
                    const role = el.getAttribute('role') || '';
                    const isInteractive = interactive.has(el.tagName) || interactiveRoles.has(role);
                    const rawText = el.innerText?.trim() || '';
                    const text = rawText.substring(0, 100);
                    const hasUsefulText = text.length > 2 && text.length < 150;

                    if (isInteractive || (hasUsefulText && contentTags.has(el.tagName))) {
                        const parent = el.parentElement;
                        // 限制文本长度避免巨大元素
                        const displayText = rawText.length > 80 ? rawText.substring(0, 80) + '...' : rawText;
                        result.push({
                            tag: tag,
                            text: displayText.replace(/\\n/g, ' ').substring(0, 80),
                            classes: (el.className?.toString() || '').substring(0, 200),
                            aria: el.getAttribute('aria-label') || '',
                            type: el.getAttribute('type') || '',
                            placeholder: el.getAttribute('placeholder') || '',
                            name: el.getAttribute('name') || '',
                            title: el.getAttribute('title') || '',
                            testid: el.getAttribute('data-testid') || '',
                            href: el.getAttribute('href') || '',
                            value: (el.value || '').substring(0, 100),
                            disabled: el.disabled || false,
                            readonly: el.readOnly || false,
                            role: role,
                            depth: depth,
                            dom_path: path,
                            parent_tag: parent?.tagName?.toLowerCase() || '',
                            parent_classes: (parent?.className?.toString() || '').substring(0, 100),
                            visible: el.offsetParent !== null || el.tagName === 'BODY' || getComputedStyle(el).position === 'fixed',
                        });
                    }

                    for (const child of el.children) {
                        walk(child, depth + 1, path + ' > ' + tag);
                    }
                }

                walk(document.body, 0, 'body');
                return result;
            }""", {"maxDepth": max_depth, "maxElements": max_elements})

            elements = []
            for data in elements_data:
                if not data.get('visible'):
                    continue
                el = ElementInfo(
                    tag=data['tag'],
                    text=data.get('text', ''),
                    selector=self._build_selector(
                        data['tag'], data.get('text', ''), data.get('aria', ''),
                        data.get('classes', ''), data.get('title', ''), data.get('testid', '')
                    ),
                    aria_label=data.get('aria', ''),
                    classes=data.get('classes', '').split() if data.get('classes') else [],
                    attributes={
                        'type': data.get('type', ''), 'placeholder': data.get('placeholder', ''),
                        'name': data.get('name', ''), 'title': data.get('title', ''),
                        'data-testid': data.get('testid', ''),
                    },
                    dom_path=data.get('dom_path', ''),
                    parent_tag=data.get('parent_tag', ''),
                    parent_classes=data.get('parent_classes', '').split() if data.get('parent_classes') else [],
                    is_disabled=data.get('disabled', False),
                    is_readonly=data.get('readonly', False),
                    href=data.get('href', ''),
                    value=data.get('value', ''),
                    role=data.get('role', ''),
                    depth=data.get('depth', 0),
                )
                elements.append(el)
            return elements
        except Exception:
            # 回退到旧的扁平收集
            return await self.collect_interactive_elements()

    def format_elements_hierarchical(self, elements: list[ElementInfo], max_per_region: int = 30) -> str:
        """将元素按 DOM 区域分组格式化，让 AI 理解页面结构"""
        regions: dict[str, list[ElementInfo]] = {}
        for el in elements:
            region_key = self._identify_region(el)
            if region_key not in regions:
                regions[region_key] = []
            regions[region_key].append(el)

        lines = []
        for region_name, region_elements in regions.items():
            lines.append(f"\n--- {region_name} ({len(region_elements)}个元素) ---")
            for i, el in enumerate(region_elements[:max_per_region]):
                parts = [f"  [{i}] <{el.tag}>"]
                if el.text:
                    parts.append(f"text='{el.text[:50]}'")
                if el.role:
                    parts.append(f"role='{el.role}'")
                if el.attributes.get("placeholder"):
                    parts.append(f"placeholder='{el.attributes['placeholder']}'")
                if el.aria_label:
                    parts.append(f"aria='{el.aria_label}'")
                if el.is_disabled:
                    parts.append("DISABLED")
                if el.href:
                    parts.append(f"href='{el.href[:50]}'")
                if el.selector:
                    parts.append(f"-> {el.selector}")
                lines.append(" ".join(parts))
        return "\n".join(lines)

    def _identify_region(self, el: ElementInfo) -> str:
        """根据 DOM 路径和 class 识别元素所属的功能区域"""
        path = el.dom_path.lower()
        classes = " ".join(el.parent_classes + el.classes).lower()

        if any(k in path or k in classes for k in ['nav', 'menu', 'sidebar', 'header', 'menubar']):
            return "导航/菜单区域"
        if any(k in path or k in classes for k in ['search', 'filter', 'toolbar']):
            return "搜索/工具栏区域"
        if any(k in path or k in classes for k in ['form', 'modal', 'dialog', 'login']):
            return "表单/弹窗区域"
        if any(k in path or k in classes for k in ['list', 'table', 'card', 'content', 'main', 'container']):
            return "内容/列表区域"
        if any(k in path or k in classes for k in ['footer', 'pagination', 'pager']):
            return "底部/分页区域"
        return "其他区域"

    def _build_selector(self, tag: str, text: str, aria: str, classes: str, title: str = "", testid: str = "") -> str:
        """构建选择器 — 按优先级：data-testid > aria-label > title > text > class"""
        if testid:
            return f'{tag}[data-testid="{testid}"]'
        if aria and len(aria) < 80:
            return f'{tag}[aria-label="{aria}"]'
        if title and len(title) < 80:
            return f'{tag}[title="{title}"]'
        if text and len(text) < 50:
            return f"{tag}:has-text('{text}')"
        if classes:
            first_class = classes.split()[0]
            return f"{tag}.{first_class}"
        return tag

    async def _extract_icon_text(self, el, classes: str, aria: str, title: str) -> str:
        """从图标按钮中提取有意义的文字描述"""
        # 1. aria-label 已经有了，直接返回
        if aria:
            return aria
        # 2. title 属性
        if title:
            return title
        # 3. 从图标 class 推断功能
        icon_map = {
            "back": "返回", "close": "关闭", "return": "返回",
            "arrow-left": "返回", "arrow-right": "前进",
            "menu": "菜单", "search": "搜索", "edit": "编辑",
            "delete": "删除", "trash": "删除", "save": "保存",
            "plus": "添加", "minus": "减少", "settings": "设置",
            "home": "首页", "user": "用户", "logout": "退出",
            "prev": "上一步", "next": "下一步",
        }
        classes_lower = classes.lower()
        for keyword, desc in icon_map.items():
            if keyword in classes_lower:
                return desc
        # 4. 尝试从子元素获取文字（span、svg title 等）
        try:
            child_text = await el.evaluate("""el => {
                // 检查子 span
                const span = el.querySelector('span');
                if (span && span.textContent.trim()) return span.textContent.trim();
                // 检查 svg title
                const svgTitle = el.querySelector('svg title');
                if (svgTitle) return svgTitle.textContent.trim();
                // 检查 img alt
                const img = el.querySelector('img');
                if (img && img.alt) return img.alt;
                return '';
            }""")
            if child_text:
                return child_text[:50]
        except Exception:
            pass
        return ""

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

    def _on_console(self, msg):
        """捕获浏览器控制台日志"""
        self.console_logs.append({
            "type": msg.type,
            "text": msg.text[:500],
            "timestamp": asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0,
        })
        # 只保留最近 200 条
        if len(self.console_logs) > 200:
            self.console_logs = self.console_logs[-100:]

    def _on_page_error(self, error):
        """捕获页面 JS 错误"""
        self.console_logs.append({
            "type": "pageerror",
            "text": str(error)[:500],
            "timestamp": asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0,
        })

    def get_console_errors(self, since: int = 0) -> list[str]:
        """获取指定时间之后的控制台错误，用于判断操作是否引发 JS 错误"""
        errors = []
        for log in self.console_logs[since:]:
            if log["type"] in ("error", "pageerror", "warning"):
                errors.append(f"[{log['type']}] {log['text']}")
        return errors

    def console_log_count(self) -> int:
        """返回当前日志条数，用于标记时间点"""
        return len(self.console_logs)
