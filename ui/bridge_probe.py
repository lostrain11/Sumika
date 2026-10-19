"""Verify the loopback bridge against OS process identity and installation scope."""
import argparse
import json
import socket
import urllib.request
from pathlib import Path
from sumika_next.runtime_ownership import process_identity
from sumika_next.socket_ownership import listener_pids


def probe(root, settings, port):
    try:
        # Windows loopback refusal may take about two seconds; a one-second
        # timeout incorrectly classifies an unused port as an unknown listener.
        with socket.create_connection(('127.0.0.1', port), timeout=5):
            pass
    except ConnectionRefusedError:
        return 2
    except OSError:
        return 3
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/instance', timeout=3) as response:
            data = json.loads(response.read(8192))
        if (data.get('kind') != 'sumika-ui-bridge' or type(data.get('pid')) is not int
                or data.get('root') != str(Path(root).resolve())
                or data.get('settings') != str(Path(settings).resolve())):
            return 3
        creation = process_identity(data['pid'])
        if creation is None or creation != data.get('creation'):
            return 3
        if listener_pids(port) != {data['pid']}:
            return 3
        return 0
    except (OSError, ValueError, KeyError):
        return 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('invalid port')
    raise SystemExit(probe(args.root, args.settings, args.port))


if __name__ == '__main__':
    main()
