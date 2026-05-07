"""页面语义快照 — 用 page.evaluate() 收集可交互元素，输出结构化 SemanticSnapshot"""

import re
from dataclasses import dataclass, field


@dataclass
class LocatorCandidate:
    strategy: str       # testid / role / label / placeholder / text / css / xpath
    value: str = ""
    role: str = ""
    name: str = ""

    def to_dict(self) -> dict:
        d = {"strategy": self.strategy}
        if self.value:
            d["value"] = self.value
        if self.role:
            d["role"] = self.role
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class SnapshotElement:
    ref: str
    tag: str
    role: str = ""
    name: str = ""
    text: str = ""
    placeholder: str = ""
    visible: bool = True
    enabled: bool = True
    locator_candidates: list[LocatorCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "ref": self.ref,
            "tag": self.tag,
            "role": self.role,
            "name": self.name,
            "visible": self.visible,
            "enabled": self.enabled,
        }
        if self.text:
            d["text"] = self.text
        if self.placeholder:
            d["placeholder"] = self.placeholder
        if self.locator_candidates:
            d["locator_candidates"] = [c.to_dict() for c in self.locator_candidates]
        return d


@dataclass
class SnapshotSection:
    name: str
    type: str           # navigation / search / form / content / toolbar / footer / modal
    elements: list[SnapshotElement] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "elements": [e.to_dict() for e in self.elements],
        }


@dataclass
class SemanticSnapshot:
    url: str
    title: str
    page_type: str = ""
    sections: list[SnapshotSection] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "page_type": self.page_type,
            "sections": [s.to_dict() for s in self.sections],
        }

    def find_element(self, ref: str) -> SnapshotElement | None:
        for section in self.sections:
            for el in section.elements:
                if el.ref == ref:
                    return el
        return None

    def all_elements(self) -> list[SnapshotElement]:
        result = []
        for section in self.sections:
            result.extend(section.elements)
        return result


# page.evaluate 中执行的 JS：收集可交互元素
_COLLECT_JS = """
() => {
    const results = [];
    const seen = new Set();

    function isVisible(el) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function getRole(el) {
        if (el.role) return el.role;
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        const map = {
            'a': 'link', 'button': 'button', 'input': type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : type === 'submit' ? 'button' : 'textbox',
            'select': 'combobox', 'textarea': 'textbox', 'nav': 'navigation',
            'h1': 'heading', 'h2': 'heading', 'h3': 'heading', 'h4': 'heading', 'h5': 'heading', 'h6': 'heading',
        };
        return map[tag] || '';
    }

    function getName(el) {
        // aria-label > aria-labelledby > label[for] > title > text content > placeholder > type兜底
        let name = el.getAttribute('aria-label') || '';
        if (!name) {
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
                const labelEl = document.getElementById(labelledBy);
                if (labelEl) name = labelEl.textContent.trim();
            }
        }
        // label[for=id] 关联
        if (!name && el.id) {
            const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (label) name = label.textContent.trim();
        }
        // 父级 <label> 包裹
        if (!name) {
            const parentLabel = el.closest('label');
            if (parentLabel) {
                const text = parentLabel.textContent.trim().replace(/\\s+/g, ' ');
                if (text.length <= 100) name = text;
            }
        }
        if (!name) name = el.getAttribute('title') || '';
        if (!name && ['button', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'label', 'span', 'div', 'li', 'td', 'th'].includes(el.tagName.toLowerCase())) {
            const text = el.textContent.trim().replace(/\\s+/g, ' ');
            if (text.length > 0 && text.length <= 100) name = text;
        }
        if (!name) name = el.getAttribute('placeholder') || '';
        // type=password 兜底
        if (!name && el.type === 'password') name = '密码';
        // input[type] 兜底
        if (!name && el.tagName.toLowerCase() === 'input' && el.type) {
            const typeNames = {text: '文本', email: '邮箱', tel: '电话', number: '数字', search: '搜索', url: '网址'};
            name = typeNames[el.type] || '';
        }
        return name;
    }

    function getLocatorCandidates(el) {
        const candidates = [];
        const tag = el.tagName.toLowerCase();

        // 1. data-testid
        const testid = el.getAttribute('data-testid') || el.getAttribute('data-test');
        if (testid) candidates.push({strategy: 'testid', value: testid});

        // 2. role + name
        const role = getRole(el);
        const name = getName(el);
        if (role && name) candidates.push({strategy: 'role', role: role, name: name});

        // 3. label
        const label = el.getAttribute('aria-label');
        if (label) candidates.push({strategy: 'label', value: label});

        // 4. placeholder
        const placeholder = el.getAttribute('placeholder');
        if (placeholder) candidates.push({strategy: 'placeholder', value: placeholder});

        // 5. text (for buttons, links)
        if (['button', 'a'].includes(tag)) {
            const text = el.textContent.trim().replace(/\\s+/g, ' ');
            if (text && text.length <= 50) candidates.push({strategy: 'text', value: text});
        }

        // 6. id (as CSS)
        const id = el.id;
        if (id && !id.match(/^[a-f0-9-]{20,}$/i)) candidates.push({strategy: 'css', value: '#' + CSS.escape(id)});

        // 7. name attribute
        const nameAttr = el.getAttribute('name');
        if (nameAttr) candidates.push({strategy: 'css', value: tag + '[name=\"' + nameAttr + '\"]'});

        return candidates;
    }

    // 收集所有可交互元素
    const interactiveSelectors = 'button, a[href], input, select, textarea, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [role="textbox"], [role="combobox"], [role="checkbox"], [role="radio"], [role="switch"], [role="treeitem"], [role="option"], [contenteditable="true"]';

    const allEls = document.querySelectorAll(interactiveSelectors);
    for (const el of allEls) {
        if (seen.has(el)) continue;
        if (!isVisible(el)) continue;
        seen.add(el);

        const rect = el.getBoundingClientRect();
        results.push({
            tag: el.tagName.toLowerCase(),
            role: getRole(el),
            name: getName(el),
            text: (el.textContent || '').trim().replace(/\\s+/g, ' ').substring(0, 200),
            placeholder: el.getAttribute('placeholder') || '',
            aria_label: el.getAttribute('aria-label') || '',
            testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
            classes: el.className ? el.className.split(/\\s+/).filter(c => c) : [],
            href: el.getAttribute('href') || '',
            rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
            locator_candidates: getLocatorCandidates(el),
            // 分类线索
            dom_path: _getDomPath(el),
        });
    }

    function _getDomPath(el) {
        const parts = [];
        let cur = el;
        while (cur && cur !== document.body && parts.length < 5) {
            let part = cur.tagName.toLowerCase();
            if (cur.id) part += '#' + cur.id;
            else if (cur.className && typeof cur.className === 'string') {
                const cls = cur.className.split(/\\s+/).filter(c => c && !c.match(/^[a-f0-9-]{10,}$/i)).slice(0, 2).join('.');
                if (cls) part += '.' + cls;
            }
            parts.unshift(part);
            cur = cur.parentElement;
        }
        return parts.join(' > ');
    }

    return results;
}
"""


def _classify_section(dom_path: str, classes: list[str], tag: str, name: str) -> str:
    """根据 DOM 路径和 class 推断元素所属的功能区域"""
    path_lower = dom_path.lower()
    class_str = " ".join(classes).lower()
    combined = path_lower + " " + class_str

    if any(k in combined for k in ["nav", "header", "menu", "sidebar", "side-bar"]):
        return "navigation"
    if any(k in combined for k in ["search", "filter", "toolbar", "action-bar"]):
        return "search"
    if any(k in combined for k in ["modal", "dialog", "drawer", "popup", "overlay"]):
        return "modal"
    if any(k in combined for k in ["footer", "pagination", "pager"]):
        return "footer"
    if any(k in combined for k in ["form", "login", "signup", "register"]):
        return "form"
    if tag in ("input", "select", "textarea") and "search" not in combined:
        return "form"
    return "content"


_SECTION_NAMES = {
    "navigation": "导航区",
    "search": "搜索/工具栏",
    "form": "表单区",
    "content": "内容区",
    "toolbar": "工具栏",
    "footer": "底部/分页",
    "modal": "弹窗/对话框",
}


def _build_ref(index: int) -> str:
    return f"el_{index:03d}"


async def take_snapshot(page) -> SemanticSnapshot:
    """对当前页面采集语义快照"""
    url = page.url
    title = await page.title()

    raw_elements = await page.evaluate(_COLLECT_JS)

    # 按功能区域分组
    sections_map: dict[str, list] = {}
    for i, raw in enumerate(raw_elements):
        section_type = _classify_section(
            raw.get("dom_path", ""),
            raw.get("classes", []),
            raw.get("tag", ""),
            raw.get("name", ""),
        )
        if section_type not in sections_map:
            sections_map[section_type] = []

        el = SnapshotElement(
            ref=_build_ref(i),
            tag=raw.get("tag", ""),
            role=raw.get("role", ""),
            name=raw.get("name", ""),
            text=raw.get("text", ""),
            placeholder=raw.get("placeholder", ""),
            visible=True,
            enabled=True,
            locator_candidates=[
                LocatorCandidate(
                    strategy=c.get("strategy", ""),
                    value=c.get("value", ""),
                    role=c.get("role", ""),
                    name=c.get("name", ""),
                )
                for c in raw.get("locator_candidates", [])
            ],
        )
        sections_map[section_type].append(el)

    # 构建 sections（按类型排序，navigation 在前）
    section_order = ["navigation", "search", "form", "modal", "content", "toolbar", "footer"]
    sections = []
    for st in section_order:
        if st in sections_map:
            sections.append(SnapshotSection(
                name=_SECTION_NAMES.get(st, st),
                type=st,
                elements=sections_map[st],
            ))
    # 处理未分类的
    for st, els in sections_map.items():
        if st not in section_order:
            sections.append(SnapshotSection(
                name=_SECTION_NAMES.get(st, st),
                type=st,
                elements=els,
            ))

    # 推断 page_type
    page_type = _infer_page_type(url, title, raw_elements)

    return SemanticSnapshot(
        url=url,
        title=title,
        page_type=page_type,
        sections=sections,
    )


def _infer_page_type(url: str, title: str, elements: list[dict]) -> str:
    """根据 URL 和元素推断页面类型"""
    url_lower = url.lower()
    title_lower = title.lower()

    if "login" in url_lower or "登录" in title_lower:
        return "login"
    if "list" in url_lower or "index" in url_lower:
        return "list"
    if "detail" in url_lower or "view" in url_lower:
        return "detail"
    if "edit" in url_lower or "form" in url_lower:
        return "form"
    if "dashboard" in url_lower or "首页" in title_lower:
        return "dashboard"

    # 根据元素类型推断
    input_count = sum(1 for e in elements if e.get("tag") in ("input", "textarea", "select"))
    link_count = sum(1 for e in elements if e.get("tag") == "a")

    if input_count > 5:
        return "form"
    if link_count > 10:
        return "list"

    return "unknown"
