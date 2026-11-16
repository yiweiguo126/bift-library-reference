#!/usr/bin/env python3
"""兼容入口：等价于 python3 scripts/fetch_space_service.py --page yanxue。

2026-11-16 起空间服务下「研学空间预约」「开放时间」共用 fetch_space_service.py；
本文件保留旧命令名，避免既有调用失效。
"""

import os
import runpy
import sys

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_space_service.py")
sys.argv = [TARGET, "--page", "yanxue"] + sys.argv[1:]
runpy.run_path(TARGET, run_name="__main__")
