import os
import subprocess
import sys

# 本文件仅用于本地临时启动真实模型服务，不纳入版本库。
os.environ["SENSENOVA_API_KEY"] = "sk-RAJS1wDNHI83ixs1rh7RxODcurHQxVWE"
subprocess.run([
    sys.executable, "-m", "metamorph.cli", "serve",
    "--provider", "sensenova", "--port", "8787",
], env=os.environ)
