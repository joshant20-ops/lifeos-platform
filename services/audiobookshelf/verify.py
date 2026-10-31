#!/usr/bin/env python3
"""Read-only, fixed-endpoint HTTP proof. Not a playback or deployment proof."""
import json
import sys
import urllib.error
import urllib.request


def main():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:13378/ping', timeout=10) as response:
            body = response.read(4097)
            if response.status != 200 or len(body) > 4096:
                raise ValueError('invalid ping response')
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get('success') is not True:
                raise ValueError('ping unsuccessful')
        with opener.open('http://127.0.0.1:13378/status', timeout=10) as response:
            payload = json.loads(response.read(4096))
            if not isinstance(payload, dict) or payload.get('app') != 'audiobookshelf' or payload.get('serverVersion') != '2.37.2' or payload.get('isInit') is not True:
                raise ValueError('wrong application or uninitialized server')
        print('AUDIOBOOKS_HTTP=PASS')
        print('AUDIOBOOKS_PING=PASS')
        print('PLAYBACK_VERIFIED=NO')
        return 0
    except (OSError, ValueError, urllib.error.URLError):
        print('AUDIOBOOKS_HTTP=FAIL')
        print('PLAYBACK_VERIFIED=NO')
        return 1


if __name__ == '__main__':
    sys.exit(main())
