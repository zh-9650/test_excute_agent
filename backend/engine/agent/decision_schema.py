"""AI Decision JSON Schema — 定义 AI 每次决策的输出格式"""

# 支持的动作类型
VALID_ACTIONS = [
    "navigate",
    "click",
    "fill",
    "hover",
    "select_option",
    "upload",
    "wait",
    "press_key",
    "assert_visible",
    "assert_text",
    "assert_url",
    "done",         # 当前步骤完成
    "blocked",      # 无法执行
]

# AI Decision JSON Schema（用于 OpenAI function calling 的 parameters）
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": VALID_ACTIONS,
            "description": "要执行的动作类型"
        },
        "target_ref": {
            "type": "string",
            "description": "目标元素的 ref（来自 snapshot），如 el_001"
        },
        "locator": {
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "enum": ["testid", "role", "label", "placeholder", "text", "css", "xpath"],
                },
                "value": {"type": "string"},
                "role": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["strategy"],
            "description": "元素定位策略（优先使用 snapshot 中的 locator_candidates，或自行判断）"
        },
        "value": {
            "type": "string",
            "description": "操作值（fill 的输入内容、select_option 的选项值、navigate 的 URL 等）"
        },
        "reason": {
            "type": "string",
            "description": "决策理由，说明为什么选择这个动作"
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "决策置信度 0-1"
        }
    },
    "required": ["action", "reason", "confidence"]
}


# OpenAI function calling 格式的 tool 定义
BROWSER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "snapshot",
            "description": "采集当前页面快照。注意：页面快照已在步骤开始时自动采集并提供给你，通常不需要再次调用。只有在执行操作后页面发生重大变化时才需要重新采集。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "点击页面元素",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {
                        "type": "string",
                        "description": "元素的 ref（来自 snapshot），如 el_001"
                    },
                    "locator": {
                        "type": "object",
                        "properties": {
                            "strategy": {"type": "string", "enum": ["testid", "role", "label", "placeholder", "text", "css"]},
                            "value": {"type": "string"},
                            "role": {"type": "string"},
                            "name": {"type": "string"},
                        },
                        "description": "直接指定定位策略（优先于 ref）"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "填写输入框",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "输入框的 ref"},
                    "value": {"type": "string", "description": "要填写的内容"},
                    "locator": {
                        "type": "object",
                        "properties": {
                            "strategy": {"type": "string"},
                            "value": {"type": "string"},
                        },
                    }
                },
                "required": ["value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hover",
            "description": "悬停在元素上（用于触发下拉菜单等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "元素的 ref"},
                    "locator": {"type": "object", "properties": {"strategy": {"type": "string"}, "value": {"type": "string"}}},
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_option",
            "description": "选择下拉框选项",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "下拉框的 ref"},
                    "value": {"type": "string", "description": "选项值"},
                    "locator": {"type": "object", "properties": {"strategy": {"type": "string"}, "value": {"type": "string"}}},
                },
                "required": ["value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "导航到指定 URL",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "按下键盘按键",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "按键名称，如 Enter, Escape, Tab"}
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "等待指定毫秒数",
            "parameters": {
                "type": "object",
                "properties": {
                    "ms": {"type": "integer", "description": "等待时间（毫秒）", "default": 1000}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "截取当前页面截图",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "截图保存路径（可选）"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "expect_visible",
            "description": "断言指定元素在页面上可见",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "description": "元素的 ref"},
                    "locator": {"type": "object", "properties": {"strategy": {"type": "string"}, "value": {"type": "string"}}},
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "expect_text",
            "description": "断言页面包含指定文本",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "期望的文本内容"}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "expect_url",
            "description": "断言当前 URL 包含指定字符串",
            "parameters": {
                "type": "object",
                "properties": {
                    "url_pattern": {"type": "string", "description": "URL 中应包含的字符串"}
                },
                "required": ["url_pattern"]
            }
        }
    },
]


def validate_decision(decision: dict) -> tuple[bool, str]:
    """校验 AI Decision 是否合法"""
    action = decision.get("action", "")
    if not action:
        return False, "缺少 action 字段"
    if action not in VALID_ACTIONS:
        return False, f"未知的 action: {action}"

    if action in ("click", "fill", "hover", "select_option", "assert_visible"):
        if not decision.get("target_ref") and not decision.get("locator"):
            return False, f"动作 {action} 需要 target_ref 或 locator"

    if action == "fill" and not decision.get("value"):
        return False, "fill 动作需要 value"

    if action == "navigate" and not decision.get("value"):
        return False, "navigate 动作需要 value（URL）"

    if action == "select_option" and not decision.get("value"):
        return False, "select_option 动作需要 value"

    confidence = decision.get("confidence", 0)
    if not (0 <= confidence <= 1):
        return False, f"confidence 应在 0-1 之间，实际: {confidence}"

    return True, ""
