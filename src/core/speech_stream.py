"""逐步接收中日文本，保留完整短句；未闭合的思考、代码与链接不进入朗读。"""
import re


def readable_prefix(text):
    output, index = [], 0
    while index < len(text):
        char = text[index]
        if char == "!" and index + 1 == len(text):
            break  # 等待下一字符，区分叹号和跨 chunk 的 Markdown 图片。
        if char == "<":
            end = text.find(">", index + 1)
            if end < 0:
                break
            if re.match(r"<think(?:\s|>)", text[index:end + 1], re.I):
                close = re.search(r"</think\s*>", text[end + 1:], re.I)
                if not close:
                    break
                index = end + 1 + close.end()
            else:
                index = end + 1
            continue
        if char == "`":
            match = re.match(r"`+", text[index:])
            delimiter = match[0]
            end = text.find(delimiter, index + len(delimiter))
            if end < 0:
                break
            index = end + len(delimiter)
            continue
        image = text.startswith("![", index)
        if char == "[" or image:
            start = index + int(image)
            end = text.find("]", start + 1)
            if end < 0 or end + 1 == len(text):
                break
            if text[end + 1] == "(":
                depth, cursor = 1, end + 2
                while cursor < len(text) and depth:
                    depth += (text[cursor] == "(") - (text[cursor] == ")")
                    cursor += 1
                if depth:
                    break
                if not image:
                    output.append(text[start + 1:end])
                index = cursor
                continue
        url = re.match(r"https?://", text[index:], re.I)
        if url:
            end = re.search(r"[\s。！？]", text[index:])
            if not end:
                break
            index += end.start()
            continue
        output.append(char)
        index += 1
    value = "".join(output)
    value = re.sub(r"(?m)^[ \t]*(?:[-*+][ \t]+|\d+[.)][ \t]+|#{1,6}[ \t]*)", "", value)
    return re.sub(r"[*#_\[\]]", "", value).lstrip()


class SentenceStream:
    def __init__(self, limit=500, segment_size=160):
        self.limit, self.segment_size = limit, segment_size
        self.raw, self.committed = "", ""
        self.consumed, self.spoken_chars = 0, 0
        self.revised = False

    def feed(self, chunk):
        self.raw += chunk
        return self._drain(readable_prefix(self.raw), False)

    def finish(self, text):
        clean = readable_prefix(text + " ")
        # 后端的最终结果可能补全 delta；已经读过的前缀不能重复播放。
        if self.spoken_chars and not clean.startswith(self.committed):
            self.revised = True
            return []
        self.raw = text
        self.consumed = len(self.committed)
        return self._drain(clean, True)

    def _drain(self, clean, final):
        result = []
        while self.consumed < len(clean) and self.spoken_chars < self.limit:
            start, end = self.consumed, None
            for index in range(start, min(len(clean), start + self.segment_size)):
                char = clean[index]
                period = char == "." and (index + 1 < len(clean) and clean[index + 1].isspace() or final and index + 1 == len(clean))
                if char in "。！？!?\n" or period:
                    end = index + 1
                    while end < len(clean) and clean[end] in '。！？!?」』”’\"':
                        end += 1
                    break
            if end is None:
                if len(clean) - start >= self.segment_size:
                    end = start + self.segment_size
                    # 长句优先在逗号、分号或空格处切分，避免单句积压。
                    soft = max(clean.rfind(char, start + 40, end) for char in "，、；;, ")
                    if soft >= start + 40:
                        end = soft + 1
                elif final:
                    end = len(clean)
                else:
                    break
            text = clean[start:end].strip()
            remaining = self.limit - self.spoken_chars
            if len(text) > remaining:
                text = text[:remaining].rstrip()
            if any(char.isalnum() for char in text):
                result.append(text)
                self.spoken_chars += len(text)
                self.committed = clean[:end]
            self.consumed = end
        return result
