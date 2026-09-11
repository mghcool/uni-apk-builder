#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uni-app Android 离线打包服务 —— 入口文件（启动 HTTP 服务）

启动：
    python3 server.py            # 端口见 builder/config.py 的 PORT（默认 80）

接口：
    POST /api/build?package=<包名>&ksPwd=<证书密码>&ksAlias=<别名>&appkey=<离线AppKey>
        请求体：zip 压缩包的原始字节流，结构：
            /app            uni-app 前端构建产物（应用名/AppID/版本/权限等元数据从其中的 manifest.json 读取）
            /icons          应用图标，命名 <宽>x<高>.png（36/48/72/96/144/192）
            /app.keystore   签名证书（别名密码自动使用证书密码）
        响应：text/event-stream，逐行输出构建日志，
            以 "=== 构建结束 (exit=0)" 或 "=== 构建结束 (exit=1)" 行收尾
        并发：同一时刻仅允许一个构建，占用中返回 HTTP 409
    GET /api/download       下载最新一次构建成功产出的 APK（服务端只保留最新一个）
    GET /                   静态说明页（wwwroot/ 目录）

Docker 挂载：
    ./uni-app-sdk -> /data/uni-app-sdk   uni-app 离线打包 SDK（按 compilerVersion 匹配子目录）
    gradle-cache 卷 -> /gradle-cache     Gradle 缓存（命名卷，勿用 Windows 目录直挂）
    构建工作目录 /data/build（每次构建开始前清空上次产物，便于排查问题）

代码结构（builder/ 包，依赖方向单向：api -> build -> utils -> config）：
    builder/config.py  全局配置：端口、路径常量、构建锁
    builder/utils.py   通用工具：APK 查找、SDK 探测、zip 解压
    builder/build.py   构建主流程：build_project
    builder/api.py     HTTP 接口：Handler（路由 / SSE / 上传 / 下载）
"""

import os
import sys
from http.server import ThreadingHTTPServer

# 保证以任意工作目录启动时都能找到同目录下的 builder 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from builder.api import Handler
from builder.config import PORT


def main():
    httpd = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print('[uni-app-builder] server started, listening on :%d' % PORT, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == '__main__':
    main()
