"""Start an explicitly enabled, authenticated Mac gateway for headset-only chat sessions."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import ssl
from aiohttp import web
from src.core.app_config import DEFAULT_CONFIG, merge_config, read_yaml
from src.core.vision_gateway import create_app


def reference_openclaw_settings(reference_config: Path) -> dict[str, str]:
    reference_chat = read_yaml(reference_config).get('voice_chat', {}).get('openclaw', {}) if reference_config.exists() else {}
    # Read existing endpoint credentials only; never modify or start the user's Agent.
    local_gateway_file = Path.home() / '.openclaw/openclaw.json'
    local_gateway = json.loads(local_gateway_file.read_text()).get('gateway', {}) if local_gateway_file.exists() else {}
    reference_session = reference_chat.get('session') or 'agent:aemeath:main'
    return {'url': reference_chat.get('gateway') or f"ws://127.0.0.1:{local_gateway.get('port', 18789)}/ws",
            'token': reference_chat.get('token') or local_gateway.get('auth', {}).get('token', ''),
            'session': reference_session,
            'agent': reference_session.split(':')[1] if reference_session.startswith('agent:') else 'aemeath'}


def character_agent_settings(reference_config: Path) -> dict[str, object]:
    return {'roles': {'hsin': {'provider': 'hermes', 'hermes': {'transport': 'pc_bridge', 'profile': 'default'}},
                      'aemeath': {'provider': 'openclaw', 'openclaw': reference_openclaw_settings(reference_config)}}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    private_root = Path.home() / 'Library/Application Support/Hsin'
    parser.add_argument('--config', type=Path, default=private_root / 'config.local.yaml')
    parser.add_argument('--characters', type=Path, default=private_root / '.runtime/characters.json')
    parser.add_argument('--token-file', type=Path, default=private_root / 'bridge-token')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=18767)
    parser.add_argument('--runtime', type=Path, default=Path('.runtime/vision-gateway'))
    parser.add_argument('--cert', type=Path)
    parser.add_argument('--key', type=Path)
    parser.add_argument('--reference-config', type=Path, default=Path.home() / 'Library/Application Support/AemeathSpirit/config.local.yaml')
    options = parser.parse_args()
    configuration = merge_config(DEFAULT_CONFIG, read_yaml(options.config))
    configuration['vision_chat'] = character_agent_settings(options.reference_config)
    registry = json.loads(options.characters.read_text())
    profiles = {profile['voice'].get('remote_voice', 'hsin'): profile for profile in registry['profiles']}
    context = None
    if options.cert or options.key:
        if not options.cert or not options.key:
            parser.error('Both certificate and key are required')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(options.cert, options.key)
    application = create_app(configuration, profiles, options.token_file.read_text().strip(), options.runtime)
    # Access logs include neither transcript bodies nor the authorization header.
    web.run_app(application, host=options.host, port=options.port, ssl_context=context, access_log=None)


if __name__ == '__main__':
    main()
