"""Launch both real servers, rehearse, then stop only those child processes.

--browser adds Chromium UI checks (install via: cd frontend && npx playwright install chromium).
The optional PLAYWRIGHT_CHROMIUM_EXECUTABLE variable selects an existing browser.
This runner also works in environments that isolate network namespaces per command.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--browser', action='store_true')
parser.add_argument('--production', action='store_true')
args = parser.parse_args()
os.chdir(ROOT)
logs = ROOT/'artifacts'; logs.mkdir(exist_ok=True)
env = dict(os.environ, NEXT_TELEMETRY_DISABLED='1')
processes = []
handles = []
try:
    for name, cmd, cwd in [
        ('backend', [sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8000'], ROOT),
        ('frontend', ['npm','run','start' if args.production else 'dev','--','--hostname','127.0.0.1','--port','3000'], ROOT/'frontend'),
    ]:
        handle = (logs/f'{name}.log').open('w'); handles.append(handle)
        processes.append(subprocess.Popen(cmd, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True))
    with httpx.Client(trust_env=False, timeout=2) as client:
        for url in ['http://127.0.0.1:8000/api/health', 'http://127.0.0.1:3000/api/health']:
            deadline = time.monotonic()+55
            while True:
                if any(proc.poll() is not None for proc in processes):
                    raise RuntimeError('A server exited; inspect artifacts/backend.log and frontend.log.')
                try:
                    if client.get(url).status_code == 200: break
                except httpx.HTTPError: pass
                if time.monotonic() >= deadline: raise RuntimeError('Server readiness deadline exceeded: '+url)
                time.sleep(.2)
    print('Backend and frontend are ready; running the live HTTP rehearsal.', flush=True)
    subprocess.run([sys.executable,'scripts/rehearse.py','--output','docs/api-rehearsal.json'], check=True, env=env)
    if args.browser:
        subprocess.run(['node','scripts/rehearse_browser.mjs'], check=True, env=env)
    print('All live rehearsals passed.', flush=True)
finally:
    for process in reversed(processes):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)
    for handle in handles: handle.close()
