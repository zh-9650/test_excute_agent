import os
import re
import tempfile


class TestDataFactory:
    EMOJI_SET = "😀🎉🔥💯✅❌🚀⭐❤️👍👎"

    @staticmethod
    def generate_file(filename: str, size_mb: int = 1) -> str:
        path = os.path.join(tempfile.gettempdir(), f"testdata_{filename}")
        with open(path, "wb") as f:
            f.write(b"\0" * size_mb * 1024 * 1024)
        return path

    @staticmethod
    def generate_string(length: int) -> str:
        return "测" * length

    @staticmethod
    def generate_emoji_string(count: int = 5) -> str:
        return TestDataFactory.EMOJI_SET * ((count // len(TestDataFactory.EMOJI_SET)) + 1)

    @staticmethod
    def generate_html_string() -> str:
        return '<script>alert("xss")</script><img src=x onerror=alert(1)>'

    @staticmethod
    def generate_from_keyword(action: str):
        size_match = re.search(r'(\d+)\s*MB', action, re.IGNORECASE)
        if size_match:
            return TestDataFactory.generate_file(f"{size_match.group(1)}MB_file.pdf", size_mb=int(size_match.group(1)))
        char_match = re.search(r'(\d+)\s*[字符个字]', action)
        if char_match:
            return TestDataFactory.generate_string(int(char_match.group(1)))
        if "emoji" in action.lower() or "表情" in action:
            return TestDataFactory.generate_emoji_string(5)
        if "html" in action.lower() or "xss" in action.lower():
            return TestDataFactory.generate_html_string()
        return None
