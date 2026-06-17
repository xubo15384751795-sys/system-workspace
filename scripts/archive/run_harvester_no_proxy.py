#!/usr/bin/env python3
"""
Harvester 运行器 - 禁用系统代理
解决 127.0.0.1:7897 代理不可用的问题
"""

import os
import sys
import subprocess

def run_harvester_no_proxy(args=None):
    """运行 Harvester，禁用系统代理"""
    
    # 清除代理环境变量
    env = os.environ.copy()
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
        env.pop(key, None)
    
    # 构建命令
    cmd = [sys.executable, '-m', 'harvester']
    if args:
        cmd.extend(args)
    
    print(f"Running: {' '.join(cmd)}")
    print(f"Proxy disabled: YES")
    print()
    
    # 运行
    result = subprocess.run(cmd, env=env, cwd='/Users/a1/System/structural-risk-harvester')
    return result.returncode

if __name__ == '__main__':
    args = sys.argv[1:] if len(sys.argv) > 1 else ['daily-release']
    sys.exit(run_harvester_no_proxy(args))
