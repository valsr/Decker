import sys
import time

sys.stderr.write("y" * (2 * 1024 * 1024))
sys.stderr.flush()
print('{"event":"ready"}', flush=True)
time.sleep(30)
