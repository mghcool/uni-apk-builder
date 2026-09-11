# -*- coding: utf-8 -*-
"""全局配置：端口、路径常量、构建锁。
换部署环境 / 改端口 / 改挂载路径，只改这个文件。"""

import os
import threading

# server/ 目录（builder/ 的上一级），静态说明页 wwwroot/ 就在这里
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PORT = 80                                   # 服务端口
GRADLE_USER_HOME = os.environ.get('GRADLE_USER_HOME', '/gradle-cache')
GRADLE_DIST_DIR = os.environ.get('GRADLE_DIST_DIR', '')   # 镜像内 gradle zip 目录（gradle-*-bin.zip）
WWWROOT = os.path.join(HERE, 'wwwroot')     # 静态说明页目录
ANDROID_SDK_DIR = '/data/uni-app-sdk'       # uni-app 离线打包 SDK 根目录
WORK_DIR = '/data/build'                    # 构建工作目录（串行构建，固定复用）
OUTPUT_DIR = '/data/output'                 # APK 输出目录（只保留最新一个）
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 全局构建锁：同一时刻仅允许一个构建，占用中直接拒绝新请求
build_lock = threading.Lock()

# ---- 16KB 适配工具链开关（HBuilderX 4.81+ 模板）----
# True  -> 对 >= 4.81 的模板强制 compileSdk 36 / buildToolsVersion 36.0.0 / AGP 8.12.0
#          前提：镜像需预装 platforms;android-36 与 build-tools;36.0.0，
#          且 GRADLE_DIST_DIR 内有 gradle-8.14.3-bin.zip
# False -> 完全使用 SDK 模板自带的工具链配置（官方 4.81+ SDK 模板本身已按此配置）
FORCE_16K_TOOLCHAIN = True

# 强制使用的工具链版本（FORCE_16K_TOOLCHAIN = True 时生效）
TOOLCHAIN_16K = {
    'compile_sdk': 36,
    'build_tools': '36.0.0',
    'agp': '8.12.0',
}
