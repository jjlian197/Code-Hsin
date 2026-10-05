"""中日语音识别共享的角色词表；只用于解码提示，不强制替换听写结果。"""
DEFAULT_HOTWORDS = ("心", "心月狐", "御者", "鸣潮", "鳴潮", "Hsin")


def normalize_hotwords(words):
    if not isinstance(words, (list, tuple)) or len(words) > 100:
        raise ValueError("热词需要最多 100 项的字符串列表")
    result, seen = [], set()
    for word in words:
        if not isinstance(word, str) or not 1 <= len(word.strip()) <= 40 or any(c in word for c in "\r\n\t"):
            raise ValueError("每个热词需要 1–40 字符，不能包含换行或制表符")
        word = word.strip()
        identity = word.casefold()
        if identity not in seen:
            result.append(word)
            seen.add(identity)
    return result


def hotwords(config):
    return normalize_hotwords(config.get("hotwords", DEFAULT_HOTWORDS))
