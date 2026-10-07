"""Real isolated headset gateway chat/STT/TTS checks using fixed text or an explicitly selected WAV; no microphone."""
from __future__ import annotations
import argparse
import asyncio
import base64
import io
import json
from pathlib import Path
import time
import uuid
import wave
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from src.core.app_config import DEFAULT_CONFIG, merge_config, read_yaml
from src.core.vision_gateway import create_app
from tools.hsin_vision_gateway import character_agent_settings


async def verify(options: argparse.Namespace) -> None:
    private_root = Path.home() / 'Library/Application Support/Hsin'
    configuration = merge_config(DEFAULT_CONFIG, read_yaml(private_root / 'config.local.yaml'))
    configuration['vision_chat'] = character_agent_settings(Path.home() / 'Library/Application Support/AemeathSpirit/config.local.yaml')
    registry = json.loads((private_root / '.runtime/characters.json').read_text())
    profiles = {profile['voice'].get('remote_voice','hsin'): profile for profile in registry['profiles']}
    token = (private_root / 'bridge-token').read_text().strip()
    root = Path('.runtime/vision-gateway-validation')
    server = TestServer(create_app(configuration, profiles, token, root / 'sessions'))
    report = {'success': False, 'microphone_enabled': False, 'chat_provider': options.chat_provider, 'events': [], 'audio': []}
    started = time.monotonic()
    identity = uuid.uuid4().hex
    payload = {'type': 'user_text', 'turn_id': identity, 'text': '请用中文说两句简短问候，第一句说明你是谁，第二句称呼我。',
               'character_id': options.character, 'language': 'zh', }
    if options.chat_provider != 'default': payload['chat_provider'] = options.chat_provider
    if options.audio:
        payload.update(type='user_audio',audio_base64=base64.b64encode(options.audio.read_bytes()).decode(),stt_provider=options.stt_provider)
    await server.start_server()
    try:
        async with ClientSession() as client:
            async with client.ws_connect(server.make_url('/ws'),headers={'Authorization':'Bearer '+token}) as socket:
                welcome = await socket.receive_json()
                assert welcome['service']=='hsin-vision-gateway'
                # Match the original native frame type, which was silently ignored by the gateway.
                await socket.send_bytes(json.dumps(payload).encode())
                while True:
                    event = await asyncio.wait_for(socket.receive_json(), 180)
                    assert event.get('turn_id')==identity
                    report['events'].append({'type':event['type'],'seconds':round(time.monotonic()-started,3),'index':event.get('index')})
                    if event['type']=='transcript': report['transcript']=event['text']
                    if event['type']=='sentence_audio':
                        if event.get('audio_error'): raise RuntimeError(event['audio_error'])
                        await socket.send_json({'type':'playback_started','turn_id':identity,'index':event['index']})
                        encoded = base64.b64decode(event['audio_base64'])
                        with wave.open(io.BytesIO(encoded),'rb') as audio:
                            duration = audio.getnframes()/audio.getframerate()
                        root.mkdir(parents=True,exist_ok=True)
                        audio_path=root/(options.character+'-'+('text' if not options.audio else options.stt_provider)+'-'+str(event['index'])+'.wav')
                        audio_path.write_bytes(encoded)
                        report['audio'].append({'index':event['index'],'text':event['text'],'duration':duration,'path':str(audio_path)})
                        print('Real sentence audio:',event['index'],round(duration,2),flush=True)
                    if event['type']=='turn_error': raise RuntimeError(event['error'])
                    if event['type']=='turn_done': report['reply']=event['reply']; break
        report['success']=bool(report['audio'])
        report['total_seconds']=round(time.monotonic()-started,3)
    finally:
        await server.close()
        Path('.runtime/vision-'+options.character+'-'+options.chat_provider+'-'+('text' if not options.audio else options.stt_provider)+'-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({key:report[key] for key in ('success','total_seconds','reply')},ensure_ascii=False),flush=True)
    assert report['success']


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--character',choices=('hsin','aemeath'),default='aemeath')
    parser.add_argument('--audio',type=Path)
    parser.add_argument('--stt-provider',choices=('remote','zhipu'),default='remote')
    parser.add_argument('--chat-provider',choices=('default','hermes','openclaw','deepseek'),default='default')
    asyncio.run(verify(parser.parse_args()))


if __name__=='__main__': main()
