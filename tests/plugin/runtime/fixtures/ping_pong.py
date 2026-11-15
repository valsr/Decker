import sys

for line in sys.stdin:
    if '"hello"' in line:
        print('{"event":"ready"}', flush=True)
    elif '"ping"' in line:
        print('{"event":"pong"}', flush=True)
    elif '"shutdown"' in line:
        break
