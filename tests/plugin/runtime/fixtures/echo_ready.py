import sys

for line in sys.stdin:
    if '"hello"' in line:
        print('{"event":"ready","payload":{"echo":true}}', flush=True)
    if '"shutdown"' in line:
        break
