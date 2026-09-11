# -*- coding: utf-8 -*-
"""通用工具函数：APK 查找、Android SDK 探测、文件读写、zip 解压。"""

import os
import io
import zipfile

from .config import OUTPUT_DIR


def find_apk():
    """返回 OUTPUT_DIR 中最新的 APK 路径，没有则返回 None"""
    if not os.path.isdir(OUTPUT_DIR):
        return None
    apks = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.apk')]
    if not apks:
        return None
    apks.sort(key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)), reverse=True)
    return os.path.join(OUTPUT_DIR, apks[0])


def find_android_home():
    """探测 Android SDK 路径"""
    for key in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        v = os.environ.get(key)
        if v and os.path.isdir(v):
            return v
    for d in ('/opt/android-sdk', '/usr/lib/android-sdk', '/android-sdk', '/sdk', '/opt/android/sdk'):
        if os.path.isdir(d):
            return d
    return None


def _human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return '%.1f%s' % (n, unit)
        n /= 1024.0
    return '%.1fTB' % n


def _read_text(p):
    with open(p, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def _sed_inplace(path, cb):
    """读取文件 -> 用 cb 变换内容 -> 内容有变化才写回"""
    content = _read_text(path)
    new_content = cb(content)
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)


def extract_zip(data, dest):
    """把 zip 字节流解压到 dest"""
    zf = zipfile.ZipFile(io.BytesIO(data))
    for name in zf.namelist():
        name = name.replace('\\', '/')  # 统一路径分隔符
        dest_path = os.path.abspath(os.path.join(dest, name))
        if dest_path != dest and not dest_path.startswith(dest + os.sep):
            raise RuntimeError('zip 含非法路径: ' + name)
        if name.endswith('/'):
            os.makedirs(dest_path, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, 'wb') as f:
                f.write(zf.read(name))
    zf.close()
