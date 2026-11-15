import sys
import time

sys.stdout.write("x" * (8 * 1024 * 1024 + 100) + "\n")
print('{"event":"ready"}', flush=True)
time.sleep(30)
