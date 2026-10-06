"""本机Ollama原生流；思考不进入朗读，取消时关闭请求，不隐式下载模型。"""
import json

import aiohttp

from src.core.chat_preferences import reply_instruction
from src.core.hermes_bridge import local_url

DEFAULT_MODEL = 'huihui_ai/qwen3.5-abliterated:4b'
PROMPT = ('你是《鸣潮》的心（Hsin），岁主是你的身份，用户是御者。称呼用户只能用御者。'
          '语气温柔、自然、偶尔俏皮，适合朗读，不自报身份，不输出动作旁白或思考过程。'
          '当前仅有聊天能力，没有工具权限；不要声称已操作桌面、读取文件或设置计时器。'
          '安排工作时核算总时长，不编造用户未给出的时刻。'
          '心、心月狐、御者、Hsin是角色专名，保持原文。')


class OllamaBridge:
    def __init__(self, config):
        self.config, self.history = config, []
        self.warning = None

    async def chat(self, text, language, on_delta, *, reply_length='normal'):
        self.warning = None
        base = local_url(self.config.get('url', 'http://127.0.0.1:11434'), ('http',))
        thinking = self.config.get('thinking', False)
        budget = 4096 if thinking else {'short': 768, 'normal': 1536, 'detailed': 4096}[reply_length]
        locale = '请用自然日语回答用户的问题，不复述或翻译提问。' if language == 'ja' else '请用中文回答。'
        payload = {'model': self.config.get('model', DEFAULT_MODEL), 'stream': True, 'think': thinking,
                   'keep_alive': '5m', 'options': {'num_ctx': self.config.get('context_length', 4096),
                   'num_predict': budget, 'temperature': 0.2},
                   'messages': [{'role': 'system', 'content': (self.config.get('persona') or PROMPT) + locale + reply_instruction(reply_length, language)},
                                *self.history, {'role': 'user', 'content': text}]}
        parts, done = [], False
        timeout = aiohttp.ClientTimeout(total=180, connect=10, sock_read=60)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.post(base + '/api/chat', json=payload, allow_redirects=False) as response:
                if response.status != 200:
                    if response.status == 404:
                        raise RuntimeError('本机Ollama没有找到所选模型，请检查已有模型名称；不会自动下载。')
                    raise RuntimeError(f'本地模型服务暂不可用（{response.status}）')
                async for raw in response.content:
                    if not raw.strip():
                        continue
                    try:
                        frame = json.loads(raw)
                    except (ValueError, UnicodeError) as error:
                        raise RuntimeError('本地模型返回了无效的流式数据') from error
                    if frame.get('error'):
                        raise RuntimeError('本地模型生成失败，请检查模型与Ollama服务')
                    message = frame.get('message', {})
                    if message.get('tool_calls'):
                        raise RuntimeError('当前本地聊天尚未开放工具执行')
                    chunk = message.get('content', '')
                    if not isinstance(chunk, str):
                        raise RuntimeError('本地模型返回了无效文字')
                    if chunk:
                        parts.append(chunk)
                        await on_delta(chunk)
                    if frame.get('done'):
                        done = True
                        if frame.get('done_reason') == 'length':
                            self.warning = '回复达到生成预算上限，可能尚未说完；这不表示显存不足。可请求继续或关闭思考。'
                        break
        if not done:
            raise RuntimeError('本地回复连接意外中断，请重试')
        reply = ''.join(parts).strip()
        if not reply:
            raise RuntimeError('本地模型没有输出最终回复；思考可能耗尽生成预算，请关闭思考或重试。')
        self.history = (self.history + [{'role': 'user', 'content': text}, {'role': 'assistant', 'content': reply}])[-12:]
        return reply
