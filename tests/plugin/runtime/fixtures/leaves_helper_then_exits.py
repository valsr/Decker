import subprocess
import sys
import time

helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(str(helper.pid))
time.sleep(1.5)
