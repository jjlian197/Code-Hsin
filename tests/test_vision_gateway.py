from __future__ import annotations
import asyncio
import base64
import io
import json
import tempfile
from pathlib import Path
from typing import Any
import unittest
import wave
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from src.core.vision_gateway import audio_pcm, create_app


def recording() -> bytes:
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\x00\x00' * 3200)
    return output.getvalue()


class Backend:
    instances: list['Backend'] = []
    def __init__(self, provider: str, configuration: dict[str, Any]) -> None:
        self.provider = provider
        self.configuration = configuration
        self.history: list[str] = []
        self.instances.append(self)
    async def chat(self, text: str, language: str, delta: Any, **settings: Any) -> str:
        self.history.append(text)
        if text == 'blocked':
            await asyncio.sleep(30)
        await delta('第一句。')
        await delta('第二句。')
        if text == 'three':
            await delta('第三句。')
            return '第一句。第二句。第三句。'
        return '第一句。第二句。'


class Voice:
    def __init__(self, configuration: dict[str, Any], runtime: Path, voice_id: str) -> None:
        self.runtime, self.voice_id = runtime, voice_id
    def synthesize(self, text: str, language: str, speed: float) -> Path:
        self.runtime.mkdir(parents=True, exist_ok=True)
        path = self.runtime / (self.voice_id + '.wav')
        path.write_bytes(recording())
        return path
    def cancel(self) -> None: pass
    def close(self) -> None: pass


class Recognizer:
    def __init__(self, *args: Any) -> None: self._remote = self
    def transcribe(self, pcm: bytes, settings: dict[str, Any]) -> tuple[str, str, str]:
        return settings['provider'] + '录音', settings['provider'], ''
    def cancel(self) -> None: pass
    def close(self) -> None: pass


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        Backend.instances = []
        self.directory = tempfile.TemporaryDirectory()
        self.token = 't' * 64
        configuration = {'speech_bridge': {}, 'stt': {}, 'chat': {'deepseek': {'api_key': 'not exposed'},
            'openclaw': {'agent': 'hsin', 'token': 'not exposed'}}}
        self.configuration = configuration
        profiles = {role: {'name': role, 'persona': role+' persona', 'voice': {'remote_voice': role},
                    'chat': {'enabled': True, 'provider': 'deepseek'}} for role in ('hsin', 'aemeath')}
        self.server = TestServer(create_app(configuration, profiles, self.token, Path(self.directory.name),
                                           backend_factory=Backend, voice_factory=Voice, recognizer_factory=Recognizer))
        await self.server.start_server()
        self.client = ClientSession()
    async def asyncTearDown(self) -> None:
        await self.client.close(); await self.server.close(); self.directory.cleanup()
    async def connect(self):
        socket = await self.client.ws_connect(self.server.make_url('/ws'), headers={'Authorization': 'Bearer '+self.token})
        self.assertEqual((await socket.receive_json())['service'], 'hsin-vision-gateway')
        return socket
    async def turn(self, socket: Any, identity: str, **fields: Any) -> list[dict[str, Any]]:
        await socket.send_json({'type': 'user_text', 'turn_id': identity, 'text': 'hello', **fields})
        events = []
        while True:
            event = await asyncio.wait_for(socket.receive_json(), 2)
            events.append(event)
            if event['type'] in ('turn_done', 'turn_error'): break
        return events
    async def test_authentication_does_not_expose_health(self) -> None:
        async with self.client.get(self.server.make_url('/health')) as response: self.assertEqual(response.status, 401)
        async with self.client.get(self.server.make_url('/health'), headers={'Authorization': 'Bearer '+self.token}) as response:
            health = await response.json(); self.assertEqual(health['characters'], ['hsin','aemeath'])
            self.assertNotIn('not exposed', str(health))
    async def test_sentence_order_and_per_connection_history(self) -> None:
        first = await self.connect(); second = await self.connect()
        events = await self.turn(first, '1'*32)
        self.assertEqual([event['index'] for event in events if event['type']=='sentence_audio'], [0,1])
        self.assertEqual([event['text'] for event in events if event['type']=='sentence_audio'], ['第一句。','第二句。'])
        await self.turn(first, '2'*32); await self.turn(second, '3'*32)
        self.assertEqual([len(backend.history) for backend in Backend.instances], [2,1])
        await first.close(); await second.close()
    async def test_role_persona_isolation_and_two_stt_choices(self) -> None:
        socket = await self.connect()
        await self.turn(socket,'1'*32,character_id='hsin')
        await self.turn(socket,'2'*32,character_id='aemeath')
        self.assertTrue(Backend.instances[0].configuration['persona'].startswith('hsin persona'))
        self.assertTrue(Backend.instances[1].configuration['persona'].startswith('aemeath persona'))
        for index, provider in enumerate(('remote','zhipu'),3):
            events=await self.turn(socket,str(index)*32,type='user_audio',audio_base64=base64.b64encode(recording()).decode(),stt_provider=provider)
            transcript = next(event for event in events if event['type']=='transcript')
            self.assertEqual(transcript['text'], provider+'录音')
            self.assertGreaterEqual(transcript['recognition_seconds'], 0)
        await socket.close()
    async def test_interrupt_revokes_old_turn_and_next_turn_recovers(self) -> None:
        socket = await self.connect()
        await socket.send_json({'type':'user_text','turn_id':'a'*32,'text':'blocked'})
        await asyncio.sleep(.02)
        await socket.send_json({'type':'interrupt'})
        self.assertEqual((await socket.receive_json())['type'],'interrupted')
        events=await self.turn(socket,'b'*32)
        self.assertTrue(all(event['turn_id']=='b'*32 for event in events))
        await socket.close()
    async def test_invalid_audio_is_rejected_without_chat(self) -> None:
        socket=await self.connect()
        events=await self.turn(socket,'a'*32,type='user_audio',audio_base64='not a wave')
        self.assertEqual(events[-1]['type'],'turn_error')
        self.assertFalse(Backend.instances[0].history)
        await socket.close()
    async def test_native_binary_json_recording_is_processed(self) -> None:
        socket = await self.connect()
        identity = 'd' * 32
        await socket.send_bytes(json.dumps({'type': 'user_audio', 'turn_id': identity,
            'audio_base64': base64.b64encode(recording()).decode(), 'stt_provider': 'remote'}).encode())
        event = await asyncio.wait_for(socket.receive_json(), .3)
        self.assertEqual(event['type'], 'transcript')
        self.assertEqual(event['text'], 'remote录音')
        await socket.close()
    async def test_openclaw_can_be_selected_without_injecting_desktop_persona(self) -> None:
        socket = await self.connect()
        events = await self.turn(socket, 'e' * 32, chat_provider='openclaw')
        self.assertEqual(events[-1]['type'], 'turn_done')
        self.assertEqual(Backend.instances[0].configuration['agent'], 'hsin')
        self.assertNotIn('persona', Backend.instances[0].configuration)
        await socket.close()
    async def test_role_default_switches_backend_and_keeps_hsin_history(self) -> None:
        self.configuration['chat']['hermes'] = {'profile': 'wrong-local-test'}
        self.configuration['vision_chat'] = {'roles': {'hsin': {'provider': 'hermes', 'hermes': {'profile': 'default'}}, 'aemeath': {'provider': 'openclaw',
            'openclaw': {'agent': 'main', 'session': 'agent:main:main'}}}}
        socket = await self.connect()
        await self.turn(socket, '1' * 32, character_id='hsin')
        await socket.send_json({'type': 'interrupt'})
        self.assertEqual((await socket.receive_json())['type'], 'interrupted')
        await self.turn(socket, '2' * 32, character_id='aemeath')
        await self.turn(socket, '3' * 32, character_id='hsin')
        self.assertEqual([backend.provider for backend in Backend.instances], ['hermes', 'openclaw'])
        self.assertEqual(Backend.instances[0].configuration['profile'], 'default')
        self.assertNotIn('persona', Backend.instances[0].configuration)
        self.assertEqual(Backend.instances[1].configuration['session'], 'agent:main:main')
        self.assertEqual([len(backend.history) for backend in Backend.instances], [2, 1])
        await socket.close()
    async def test_audio_backpressure_needs_playback_ack_and_ignores_duplicate_ack(self) -> None:
        socket = await self.connect()
        identity = 'c' * 32
        await socket.send_json({'type':'user_text','turn_id':identity,'text':'three'})
        indices=[]
        while len(indices)<2:
            event=await socket.receive_json()
            if event['type']=='sentence_audio': indices.append(event['index'])
        self.assertEqual(indices,[0,1])
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(socket.receive_json(),.05)
        # Failed local decoding must release credit without claiming actual playback.
        for acknowledgement in ('audio_discarded', 'playback_started'):
            await socket.send_json({'type':acknowledgement,'turn_id':identity,'index':0})
        while True:
            event=await asyncio.wait_for(socket.receive_json(),1)
            if event['type']=='sentence_audio': self.assertEqual(event['index'],2)
            if event['type']=='turn_done': break
        await socket.close()
    def test_wav_validation(self) -> None:
        self.assertEqual(len(audio_pcm(base64.b64encode(recording()).decode())),6400)
        with self.assertRaises(ValueError): audio_pcm('x'*1100001)
