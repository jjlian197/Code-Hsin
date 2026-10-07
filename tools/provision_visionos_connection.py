"""Send an explicitly requested private connection to the user's installed headset app."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--gateway-url', required=True)
    parser.add_argument('--bridge-url', default='https://bridge.oieasklja.icu')
    parser.add_argument('--token-file', type=Path, default=Path.home() / 'Library/Application Support/Hsin/bridge-token')
    options = parser.parse_args()
    token = options.token_file.read_text().strip()
    if len(token) < 32 or any(character.isspace() for character in token):
        parser.error('Invalid private bridge token')
    staging = Path('.runtime/vision-provision')
    staging.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(dir=staging, suffix='.json')
    try:
        # The token is never passed on a command line or included in the signed bundle.
        with os.fdopen(descriptor, 'w') as connection_file:
            json.dump({'bridgeURL': options.bridge_url, 'gatewayURL': options.gateway_url,
                       'token': token}, connection_file)
        subprocess.run(['xcrun', 'devicectl', 'device', 'copy', 'to', '--device', options.device,
                        '--source', filename, '--destination', 'Documents/HsinConnection.json',
                        '--domain-type', 'appDataContainer', '--domain-identifier', 'com.hsin.spatial',
                        '--timeout', '60'], check=True)
    finally:
        Path(filename).unlink(missing_ok=True)
    print('Private connection delivered; the app imports it into Keychain on its next launch.')


if __name__ == '__main__':
    main()
