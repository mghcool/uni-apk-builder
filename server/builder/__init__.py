# -*- coding: utf-8 -*-
"""uni-app 离线打包服务 —— 功能模块包

模块划分（依赖方向单向，无循环引用）：
    config  全局配置：端口、路径常量、构建锁
    utils   通用工具：APK 查找、SDK 探测、文件读写、zip 解压
    build   构建主流程：build_project
    api     HTTP 接口：Handler（路由 / SSE / 上传 / 下载）
"""
