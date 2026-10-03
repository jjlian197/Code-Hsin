"""回复长度与朗读范围的共享选项。"""
REPLY_LENGTHS = {"short": "简短", "normal": "适中", "detailed": "详细"}
SPEECH_SCOPES = {"full": "全文", "sentences": "前几句", "prefix": "前几字", "off": "不自动朗读"}
PREFERENCE_KEYS = ("reply_length", "speech_scope", "speech_sentence_count", "speech_prefix_chars")


def reply_instruction(length, language):
    if language == "ja":
        return {"short": "通常は1〜3文で簡潔に答えてください。", "normal": "必要な説明を省かず、適度な長さで答えてください。",
                "detailed": "結論を先に示し、理由や具体例を十分に説明してください。"}[length] + "ユーザーが長さや形式を指定した場合はそちらを優先してください。"
    return {"short": "默认用一到三句简短回答。", "normal": "默认适中回答，保留必要说明，不必强行压缩成几句。",
            "detailed": "先给结论，再充分说明理由、步骤或例子，不因语音朗读而省略必要内容。"}[length] + "用户明确指定长度或格式时优先遵循用户要求。"
