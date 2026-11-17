import subprocess
import sys

subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print('{"event":"ready"}', flush=True)
