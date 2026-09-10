"""Render real Auto assets with fixture-only HTTP in headless Edge/Chromium.

python3 -B tests/browser_auto.py [--browser /path/to/chromium]
Uses a temporary isolated browser profile. Starts no Flask/device services.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
import tempfile

import helpers
import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser')
    parser.add_argument('--artifacts', help='optional directory for fixture screenshots')
    args = parser.parse_args()
    browser = args.browser or next((p for p in (
        r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        shutil.which('chromium'), shutil.which('chromium-browser'), shutil.which('google-chrome'))
        if p and Path(p).exists()), None)
    if not browser:
        print('NOT RUN: specify an installed Edge/Chromium with --browser')
        return 2
    client = server.app.test_client()
    state = client.get('/api/state').get_json()
    config = client.get('/api/config').get_json()
    markup = client.get('/auto').get_data(as_text=True)
    # Embed local assets, including font URLs, so no HTTP server can own devices.
    css = (helpers.ROOT / 'app/static/app.css').read_text(encoding='utf-8')
    css = re.sub(r'url\(([\'"]?)([^)\'"]+)\1\)',
                 lambda m: 'url("' + (helpers.ROOT / 'app/static' / m[2]).as_uri() + '")', css)
    markup = re.sub(r'<link[^>]+href="/static/app.css"[^>]*>', lambda m: '<style>' + css + '</style>', markup)
    for name in ('common.js', 'auto.js'):
        script = (helpers.ROOT / 'app/static' / name).read_text(encoding='utf-8')
        markup = markup.replace(f'<script src="/static/{name}"></script>', '<script>' + script + '</script>')
    setup = ('window.TEST_STATE=' + json.dumps(state) + ';window.TEST_CONFIG=' + json.dumps(config) + ';'
             'window.TEST_POSTS=[];window.fetch=async(path,opt={})=>{'
             'if(opt.method && opt.method!=="GET"){TEST_POSTS.push(path);throw Error("motion forbidden");}'
             'return {ok:true,json:async()=>path.includes("config")?TEST_CONFIG:path.includes("events")?'
             '{events:[],seq:0}:structuredClone(TEST_STATE)};};')
    markup = markup.replace('<head>', '<head><script>' + setup + '</script>')
    tests = (helpers.ROOT / 'tests/auto-page.browser.js').read_text(encoding='utf-8')
    markup = markup.replace('</body>', '<script>' + tests + '</script></body>')
    failed = 0
    with tempfile.TemporaryDirectory(prefix='agv-auto-browser-') as directory:
        page = Path(directory) / 'auto.html'
        for width, height in ((1440, 1000), (390, 844)):
            page.write_text(markup.replace('<head>', f'<head><script>window.TEST_WIDTH={width};</script>'), encoding='utf-8')
            profile = Path(directory) / f'profile-{width}'
            command = [browser, '--headless', '--disable-gpu', '--no-first-run',
                       '--no-default-browser-check', '--allow-file-access-from-files',
                       '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank']
            import websocket  # websocket-client; browser test dependency only
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=0x08000000 if os.name == 'nt' else 0)
            connection = None
            try:
                deadline = time.monotonic() + 15
                port_file = profile / 'DevToolsActivePort'
                while not port_file.exists():
                    if time.monotonic() > deadline or process.poll() is not None:
                        raise RuntimeError('browser debugging endpoint did not start')
                    time.sleep(.05)
                port = port_file.read_text().splitlines()[0]
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=5) as response:
                    targets = json.load(response)
                target = next(t for t in targets if t['type'] == 'page')
                connection = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
                number = 0
                def cdp(method, params=None):
                    nonlocal number
                    number += 1
                    connection.send(json.dumps(dict(id=number, method=method, params=params or {})))
                    while True:
                        response = json.loads(connection.recv())
                        if response.get('id') == number:
                            if 'error' in response:
                                raise RuntimeError(response['error'])
                            return response.get('result', {})
                cdp('Emulation.setDeviceMetricsOverride', dict(width=width, height=height, deviceScaleFactor=1, mobile=False))
                cdp('Page.navigate', dict(url=page.as_uri()))
                checks = None
                deadline = time.monotonic() + 10
                while checks is None and time.monotonic() < deadline:
                    result = cdp('Runtime.evaluate', dict(expression="document.getElementById('browser-results')?.textContent", returnByValue=True))
                    value = result.get('result', {}).get('value')
                    if value:
                        checks = json.loads(value)
                    else:
                        time.sleep(.05)
                if checks is None:
                    raise RuntimeError('browser fixture did not complete')
                if args.artifacts:
                    output = Path(args.artifacts).resolve()
                    output.mkdir(parents=True, exist_ok=True)
                    data = cdp('Page.captureScreenshot', dict(format='png'))['data']
                    (output / f'auto-{width}.png').write_bytes(base64.b64decode(data))
            finally:
                if connection:
                    connection.close()
                process.terminate()
                process.wait(timeout=10)
            problems = [c['name'] for c in checks if not c['pass']]
            print(f'{width}px: {len(checks)} browser checks, {len(problems)} failed')
            for problem in problems:
                print('FAIL:', problem)
            failed += len(problems)
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
