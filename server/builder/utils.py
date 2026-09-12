# -*- coding: utf-8 -*-
"""通用工具函数：APK 查找、Android SDK 探测、文件读写、zip 解压。"""

import os
import io
import re
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


class TemplateMismatch(RuntimeError):
    """SDK 模板结构与预期不符：锚点没命中，改写被静默跳过。"""


def _verify(tag, path, checks):
    """回读文件，确认期望内容确实写进去了，并返回文件内容。

    模板改写全靠文本锚点匹配，锚点一旦没命中就静默跳过（_sed_inplace 只在
    内容有变化时才写回，所以"没改成"和"已经是对的"表现完全一样）。后果是
    包名/版本号不对、没签名、启动白屏，而日志照样显示成功，等装到设备上才
    发现。所以这里一律硬失败：继续编出来也是坏包，早停比拿到坏包再排查便宜。

    checks 是列表，元素三种写法：
        '期望字符串'                   子串匹配，命中即通过
        ('报错用的说明', '期望字符串')    同上，但报错只显示说明，
                                      用于密码/AppKey 等敏感值
        ('报错用的说明', re.compile(..)) 正则匹配：用于"值固定但写法可能不同"
                                      的情况（例：buildToolsVersion 的引号
                                      单双都可能，改写会保留原引号）
    """
    text = _read_text(path)
    missing = []
    for item in checks:
        label, needle = item[:2] if isinstance(item, (tuple, list)) else (item, item)
        if isinstance(needle, re.Pattern):
            if not needle.search(text):
                missing.append(label if isinstance(label, str) else needle.pattern)
        elif needle not in text:
            missing.append(label)
    if missing:
        raise TemplateMismatch('%s 模板校验失败，以下内容没写进去: %s'
                               % (tag, '、'.join(missing)))
    return text


def extract_zip(data, dest):
    """把 zip 字节流解压到 dest"""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
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
