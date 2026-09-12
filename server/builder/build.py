#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建主流程：从解压后的压缩包目录（zip_dir）产出 APK。

对外只暴露一个函数 build_project(zip_dir, params, log)：
    zip_dir  已解压的压缩包目录（含 /app、/icons、/app.keystore）
    params   接口查询参数（package / ksPwd / ksAlias / appkey）
    log      日志回调，每行调用一次（由 api 层转发到控制台与 SSE）
"""

import os
import re
import json
import shutil
import glob
import datetime
import subprocess
import shlex

from .config import (WORK_DIR, ANDROID_SDK_DIR, OUTPUT_DIR, GRADLE_USER_HOME,
                     GRADLE_DIST_DIR, FORCE_16K_TOOLCHAIN, TOOLCHAIN_16K)
from .utils import _human_size, _read_text, _sed_inplace, find_android_home


def _xml_escape(s):
    """转义 XML 文本/属性中的特殊字符（应用名、版本号来自用户 manifest.json）"""
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def _gradle_sq(s):
    """转义 Gradle 单引号字符串中的反斜杠与单引号"""
    return str(s).replace('\\', '\\\\').replace("'", "\\'")


def _gradle_dq(s):
    """转义 Gradle 双引号字符串中的反斜杠与双引号"""
    return str(s).replace('\\', '\\\\').replace('"', '\\"')


def _as_int(v, default):
    """把 manifest 里的数值字段安全转成 int，非法时回退默认值"""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def build_project(zip_dir, params, log):
    """执行一次完整构建。构建失败的现场保留在 WORK_DIR 便于排查。"""

    def ok(msg):
        log('[OK] ' + msg)

    def warn(msg):
        log('[WARN] ' + msg)

    def err(msg):
        log('[ERROR] ' + msg)

    log('=' * 42)
    log(' uni-app Android 离线打包构建')
    log('=' * 42)

    # 清空构建工作目录：删掉上一次构建的工程与产物，
    # 本次构建失败时现场干净、方便定位问题
    work_dir = WORK_DIR
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(work_dir)

    app_www = os.path.join(zip_dir, 'app')
    app_icons = os.path.join(zip_dir, 'icons')
    app_keystore = os.path.join(zip_dir, 'app.keystore')
    manifest_path = os.path.join(app_www, 'manifest.json')

    # 构建参数来自接口查询参数（别名密码直接使用证书密码）
    APP_PACKAGE = params.get('package', '')
    KEYSTORE_PASSWORD = params.get('ksPwd', '')
    KEY_ALIAS = params.get('ksAlias', '')
    KEY_PASSWORD = KEYSTORE_PASSWORD
    DCLOUD_APPKEY = params.get('appkey', '')

    # 必填校验：zip 结构与接口参数齐全才继续
    missing = []
    if not os.path.isdir(app_www):
        missing.append('zip 内 /app 目录（uni-app 前端构建产物）')
    if not os.path.isfile(manifest_path):
        missing.append('zip 内 /app/manifest.json')
    if not os.path.isfile(app_keystore):
        missing.append('zip 内 /app.keystore')
    if not os.path.isdir(ANDROID_SDK_DIR):
        missing.append('Android-SDK 挂载目录 %s' % ANDROID_SDK_DIR)
    if not APP_PACKAGE:
        missing.append('package（包名）')
    if not KEY_ALIAS:
        missing.append('ksAlias（证书别名）')
    if not KEYSTORE_PASSWORD:
        missing.append('ksPwd（证书密码）')
    if not DCLOUD_APPKEY:
        missing.append('appkey（DCLOUD 离线 AppKey）')
    if missing:
        err('构建中止，缺失：' + '；'.join(missing))
        raise RuntimeError('配置不完整：' + ', '.join(missing))

    # ---- 步骤 1：解析 manifest.json ----
    log('步骤 1/9: 解析 manifest.json...')
    try:
        m = json.loads(_read_text(manifest_path))
    except Exception as e:
        err('manifest.json 解析失败: %s' % e)
        raise
    APPID = m.get('id', '')
    APP_NAME = m.get('name', '')
    version = m.get('version') or {}            # manifest 里可能显式写 null
    VERSION_NAME = version.get('name', '')
    VERSION_CODE = version.get('code', '')
    plus = m.get('plus') or {}
    google = (plus.get('distribute') or {}).get('google') or {}
    MIN_SDK = _as_int(google.get('minSdkVersion'), 21)
    TARGET_SDK = _as_int(google.get('targetSdkVersion'), 30)
    PERMS = [p for p in (google.get('permissions') or [])
             if isinstance(p, str) and p.strip()]
    COMPILER_VER = (plus.get('uni-app') or {}).get('compilerVersion', '')
    if not COMPILER_VER:
        err('manifest.json 缺少 plus.uni-app.compilerVersion，无法确定 SDK 版本')
        raise RuntimeError('缺少 compilerVersion')
    if not APPID:
        # 缺失时资源会被塞进 assets/apps//www，编译能过但运行必白屏
        err('manifest.json 缺少 id（uni-app AppID），无法确定资源目录')
        raise RuntimeError('缺少 AppID')
    if not str(VERSION_CODE).strip().isdigit():
        # 直接写入会得到 "versionCode "（无值），Gradle 报语法错误且难以定位
        err('manifest.json 的 version.code 缺失或非整数（当前: %r）' % VERSION_CODE)
        raise RuntimeError('version.code 非法')
    log('  AppID: %s  应用名: %s  版本: %s(%s)' % (APPID, APP_NAME, VERSION_NAME, VERSION_CODE))

    # ---- 步骤 2：按 compilerVersion 匹配离线打包 SDK ----
    log('步骤 2/9: 匹配 uni-app SDK（compilerVersion=%s）...' % COMPILER_VER)
    sdk_hits = [d for d in sorted(glob.glob(os.path.join(ANDROID_SDK_DIR, '*%s*' % COMPILER_VER)))
                if os.path.isdir(d)]
    if not sdk_hits:
        available = sorted(d for d in os.listdir(ANDROID_SDK_DIR)
                           if os.path.isdir(os.path.join(ANDROID_SDK_DIR, d))) \
            if os.path.isdir(ANDROID_SDK_DIR) else []
        err('未找到匹配 %s 的 SDK 目录；已支持: %s' % (COMPILER_VER, ', '.join(available) or '无'))
        err('可联系管理员添加，或本地执行 npx @dcloudio/uvm <版本号> 切换编译器版本')
        raise RuntimeError('找不到 SDK 目录')
    SDK_DIR = sdk_hits[0]
    ok('SDK 目录: ' + SDK_DIR)

    # ---- 步骤 3：复制模板工程并注入前端构建产物 ----
    log('步骤 3/9: 生成 Android 工程...')
    android_project = os.path.join(work_dir, 'android-project')
    if os.path.isdir(android_project):
        shutil.rmtree(android_project)                 # 清理上一次构建残留
    shutil.copytree(os.path.join(SDK_DIR, 'HBuilder-Integrate-AS'), android_project)

    simple_demo = os.path.join(android_project, 'simpleDemo')
    res_dir = os.path.join(simple_demo, 'src', 'main')

    # 解析 SDK 模板版本号（目录名如 "4.75" / "5.24"），供 Gradle 版本选择与
    # 16K 工具链判断使用；无法解析时按最旧处理
    try:
        sdk_ver = tuple(int(p) for p in os.path.basename(os.path.normpath(SDK_DIR)).split('.'))
    except ValueError:
        sdk_ver = (0,)

    # gradlew 换行符统一为 LF 并加执行权限
    gradlew = os.path.join(android_project, 'gradlew')
    if os.path.isfile(gradlew):
        with open(gradlew, 'rb') as f:
            content = f.read().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
        with open(gradlew, 'wb') as f:
            f.write(content)
        os.chmod(gradlew, 0o755)

    # 16KB 适配：对 >= 4.81 模板强制官方要求的工具链版本
    # （compileSdk 36 / buildToolsVersion 36.0.0 / AGP 8.12.0）。
    # 正常情况下 4.81+ SDK 模板已自带这些值，此处仅作兜底；
    # 需镜像预装 platforms;android-36 与 build-tools;36.0.0，否则构建会失败
    if FORCE_16K_TOOLCHAIN and sdk_ver >= (4, 81):
        demo_gradle = os.path.join(simple_demo, 'build.gradle')
        root_gradle = os.path.join(android_project, 'build.gradle')

        def _force_toolchain(content):
            cs = 'compileSdkVersion %d' % TOOLCHAIN_16K['compile_sdk']
            # buildToolsVersion 的引号单双都可能（5.24 模板用单引号），一并兼容。
            # 必须用 lambda 做替换：若用 '\\1' 分组引用，版本号开头的数字会被
            # 正则引擎拼成八进制转义（如 \136 -> '^'），产生损坏的版本号
            content = re.sub(
                r"buildToolsVersion\s+(['\"])[^'\"]*(['\"])",
                lambda m: 'buildToolsVersion %s%s%s' % (
                    m.group(1), TOOLCHAIN_16K['build_tools'], m.group(2)),
                content)
            if 'buildToolsVersion' not in content:
                # 模板未显式声明 buildToolsVersion 时，紧跟 compileSdk 插入
                content = content.replace(cs, cs + '\n        buildToolsVersion "%s"'
                                          % TOOLCHAIN_16K['build_tools'], 1)
            return re.sub(r'compileSdkVersion \d+', cs, content)
        _sed_inplace(demo_gradle, _force_toolchain)

        def _force_agp(content):
            # 兼容两种声明方式：classpath 'com.android.tools.build:gradle:x'
            # 与 plugins DSL 的 id 'com.android.application' version 'x'
            content = re.sub(r'(com\.android\.tools\.build:gradle:)[\d.]+',
                             lambda m: m.group(1) + TOOLCHAIN_16K['agp'], content)
            return re.sub(r"(id\(['\"]com\.android\.application['\"]\s+version\s+['\"])[\d.]+(['\"])",
                          lambda m: m.group(1) + TOOLCHAIN_16K['agp'] + m.group(2), content)
        _sed_inplace(root_gradle, _force_agp)
        ok('已强制 16K 工具链: compileSdk %d / buildTools %s / AGP %s'
           % (TOOLCHAIN_16K['compile_sdk'], TOOLCHAIN_16K['build_tools'], TOOLCHAIN_16K['agp']))

    # 改写 wrapper 的 distributionUrl 为镜像内本地 zip 的 file:// 路径，
    # 构建/首次运行 gradlew 时直接使用本地文件，无需联网下载。
    # 版本选择（官方 16KB 适配要求：HBuilderX 4.81+ 模板使用 AGP 8.12.0，
    # 需搭配 Gradle 8.14.3）：
    #   uni-app SDK < 4.81 -> gradle-8.11.1
    #   uni-app SDK >= 4.81 -> gradle-8.14.3
    wrapper_props = os.path.join(android_project, 'gradle', 'wrapper', 'gradle-wrapper.properties')
    if GRADLE_DIST_DIR and os.path.isdir(GRADLE_DIST_DIR) and os.path.isfile(wrapper_props):
        gradle_ver = '8.14.3' if sdk_ver >= (4, 81) else '8.11.1'
        gradle_zip = os.path.join(GRADLE_DIST_DIR, 'gradle-%s-bin.zip' % gradle_ver)
        if os.path.isfile(gradle_zip):
            # properties 文件里冒号按惯例转义（file\:///...），wrapper 读取后还原
            _sed_inplace(wrapper_props, lambda c: re.sub(
                r'distributionUrl=.*',
                lambda m: 'distributionUrl=file\\:///' + gradle_zip.lstrip('/'),
                c))
            ok('gradle 发行版: %s（本地离线）' % gradle_ver)
        else:
            warn('未找到本地 Gradle 发行版 %s，保持模板 distributionUrl 联网下载' % gradle_zip)

    # 注入前端构建产物到 assets/apps/<APPID>/www（DCloud 引擎要求的目录结构）
    example_app = os.path.join(res_dir, 'assets', 'apps', '__UNI__A')
    if os.path.isdir(example_app):
        shutil.rmtree(example_app)
    target_app = os.path.join(res_dir, 'assets', 'apps', APPID, 'www')
    os.makedirs(target_app, exist_ok=True)
    for item in os.listdir(app_www):
        s, d = os.path.join(app_www, item), os.path.join(target_app, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
    ok('应用资源已注入: assets/apps/%s/www/' % APPID)

    # ---- 步骤 4：复制基础库（官方文档要求，缺失会导致对应功能异常）----
    log('步骤 4/9: 复制基础库...')
    libs_dir = os.path.join(simple_demo, 'libs')
    if os.path.isdir(libs_dir):
        shutil.rmtree(libs_dir)
    os.makedirs(libs_dir, exist_ok=True)
    base_libs = [
        'lib.5plus.base-release.aar',       # 5+ 基础引擎（必需）
        'android-gif-drawable-1.2.29.aar',  # gif 加载（必需）
        'uniapp-v8-release.aar',            # uni-app v8 渲染引擎（必需）
        'oaid_sdk_1.0.25.aar',              # OAID 设备标识
        'install-apk-release.aar',          # App 内下载安装 APK（应用升级）
        'breakpad-build-release.aar',       # 崩溃采集
    ]
    sdk_libs_dir = os.path.join(SDK_DIR, 'SDK', 'libs')
    for lib in base_libs:
        src = os.path.join(sdk_libs_dir, lib)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(libs_dir, lib))
        else:
            warn('基础库缺失: ' + lib)
    ok('基础库复制完成（%d 个）' % len(base_libs))

    # ---- 步骤 5：注入应用图标（按密度分发）----
    log('步骤 5/9: 处理应用图标...')
    density_size = {'ldpi': 36, 'mdpi': 48, 'hdpi': 72, 'xhdpi': 96,
                    'xxhdpi': 144, 'xxxhdpi': 192}
    copied, fallback, fallback_w = 0, '', 0
    if os.path.isdir(app_icons):
        for png in glob.glob(os.path.join(app_icons, '*.png')):
            w = os.path.basename(png).split('x')[0]
            if not w.isdigit():
                continue
            w = int(w)
            for dens, sz in density_size.items():
                if w == sz:
                    ddir = os.path.join(res_dir, 'res', 'drawable-%s' % dens)
                    os.makedirs(ddir, exist_ok=True)
                    shutil.copy2(png, os.path.join(ddir, 'icon.png'))
                    copied += 1
                    if w > fallback_w:
                        fallback, fallback_w = png, w
        if fallback:
            ddir = os.path.join(res_dir, 'res', 'drawable')
            os.makedirs(ddir, exist_ok=True)
            shutil.copy2(fallback, os.path.join(ddir, 'icon.png'))
    if copied:
        ok('已注入 %d 个密度图标（最大 %dpx）' % (copied, fallback_w))
    else:
        warn('icons/ 中无标准密度图标，沿用模板默认图标')

    # 推送图标与启动界面均使用应用图标
    drawable_dir = os.path.join(res_dir, 'res', 'drawable')
    drawable_icon = os.path.join(drawable_dir, 'icon.png')
    if os.path.isfile(drawable_icon):
        shutil.copy2(drawable_icon, os.path.join(drawable_dir, 'push.png'))

    # 启动界面：删除模板 splash.png，改用白底 + 居中 logo 的 layer-list（不变形）
    for d in glob.glob(os.path.join(res_dir, 'res', 'drawable*')):
        sp = os.path.join(d, 'splash.png')
        if os.path.isfile(sp):
            os.remove(sp)
    with open(os.path.join(drawable_dir, 'splash_bg.xml'), 'w', encoding='utf-8') as f:
        f.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<layer-list xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <item>\n'
            '        <color android:color="#FFFFFF"/>\n'
            '    </item>\n'
            '    <item\n'
            '        android:width="120dp"\n'
            '        android:height="120dp"\n'
            '        android:gravity="center">\n'
            '        <bitmap android:src="@drawable/icon" android:gravity="fill"/>\n'
            '    </item>\n'
            '</layer-list>\n'
        )
    ok('启动界面已生成（白底 + 居中 logo）')

    # ---- 步骤 6：注入 SDK data 资源与应用信息 ----
    log('步骤 6/9: 注入应用信息...')
    data_dir = os.path.join(res_dir, 'assets', 'data')
    sdk_data = os.path.join(SDK_DIR, 'SDK', 'assets', 'data')
    shutil.copy2(os.path.join(sdk_data, 'dcloud_properties.xml'), data_dir)
    if os.path.isfile(os.path.join(sdk_data, 'dcloud_error.html')):
        shutil.copy2(os.path.join(sdk_data, 'dcloud_error.html'), data_dir)
    shutil.copy2(os.path.join(sdk_data, 'dcloud_control.xml'), data_dir)

    # 注意：替换内容必须由 lambda 返回。若直接把内容当替换字符串传给 re.sub，
    # 其中的 '\' 或 '\g' 会被正则引擎当转义序列处理（与下方 16K 工具链同一个坑）
    _sed_inplace(os.path.join(data_dir, 'dcloud_control.xml'), lambda c: re.sub(
        r'appid="[^"]*"', lambda m: 'appid="%s"' % _xml_escape(APPID),
        re.sub(r'appver="[^"]*"', lambda m: 'appver="%s"' % _xml_escape(VERSION_NAME), c)))

    # strings.xml 应用名（名称含 & < > 等字符时必须转义，否则 XML 解析失败）
    strings = os.path.join(res_dir, 'res', 'values', 'strings.xml')
    _sed_inplace(strings, lambda c: re.sub(
        r'<string name="app_name">[^<]*</string>',
        lambda m: '<string name="app_name">%s</string>' % _xml_escape(APP_NAME), c))

    # styles.xml 注入 SplashTheme
    styles = os.path.join(res_dir, 'res', 'values', 'styles.xml')
    _sed_inplace(styles, lambda c: c if 'SplashTheme' in c else c.replace(
        '</resources>',
        '\n    <style name="SplashTheme" parent="DCloudActivityTheme">\n'
        '        <item name="android:windowBackground">@drawable/splash_bg</item>\n'
        '    </style>\n</resources>'))

    # ---- 步骤 7：更新 build.gradle（包名/版本/ABI/依赖/签名）----
    log('步骤 7/9: 更新 build.gradle...')
    bgrade = os.path.join(simple_demo, 'build.gradle')

    def _edit_gradle(content):
        content = re.sub(r'applicationId "[^"]*"',
                         lambda m: 'applicationId "%s"' % _gradle_dq(APP_PACKAGE), content)
        content = re.sub(r'minSdkVersion \d+', 'minSdkVersion %d' % MIN_SDK, content)
        content = re.sub(r'targetSdkVersion \d+', 'targetSdkVersion %d' % TARGET_SDK, content)
        content = re.sub(r'versionCode \d+', 'versionCode %d' % int(VERSION_CODE), content)
        content = re.sub(r'versionName "[^"]*"',
                         lambda m: 'versionName "%s"' % _gradle_dq(VERSION_NAME), content)
        if 'abiFilters' not in content:
            content = content.replace(
                'multiDexEnabled true',
                "multiDexEnabled true\n        ndk {\n            abiFilters 'armeabi-v7a', 'arm64-v8a'\n        }",
                1)
        # fresco 3.4.0 + webp 相关依赖 + zip4j（模板版本偏旧，统一升级）
        content = content.replace('com.facebook.fresco:fresco:2.5.0', 'com.facebook.fresco:fresco:3.4.0')
        content = content.replace('com.facebook.fresco:animated-gif:2.5.0', 'com.facebook.fresco:animated-gif:3.4.0')
        if 'middleware' not in content:
            lines = content.split('\n')
            for i, ln in enumerate(lines):
                if 'animated-gif' in ln:
                    lines[i + 1:i + 1] = [
                        '    implementation "com.facebook.fresco:middleware:3.4.0"',
                        '    implementation "com.facebook.fresco:webpsupport:3.4.0"',
                        '    implementation "com.facebook.fresco:animated-webp:3.4.0"',
                    ]
                    break
            content = '\n'.join(lines)
        if 'zip4j' not in content:
            lines = content.split('\n')
            for i, ln in enumerate(lines):
                if 'webkit:1.5.0' in ln:
                    lines.insert(i + 1, '    implementation "net.lingala.zip4j:zip4j:2.11.5"')
                    break
            content = '\n'.join(lines)
        content = content.replace('androidx.core:core:1.1.0', 'androidx.core:core:1.6.0')
        if TARGET_SDK >= 34 and 'useLegacyPackaging' not in content:
            content = content.replace(
                'aaptOptions {',
                '    packagingOptions {\n        jniLibs {\n            useLegacyPackaging true\n        }\n    }\n\naaptOptions {',
                1)
        if 'lintOptions' not in content:
            content = content.replace(
                'aaptOptions {',
                '    lintOptions {\n        checkReleaseBuilds false\n        abortOnError false\n    }\n\naaptOptions {',
                1)
        return content
    _sed_inplace(bgrade, _edit_gradle)

    # 签名配置：证书已复制进工程，写入密码/别名
    shutil.copy2(app_keystore, simple_demo)
    kname = os.path.basename(app_keystore)

    def _edit_sign(content):
        # 证书密码/别名来自接口参数，若含 '\' 或 ' 会破坏 Gradle 语法，需先转义
        content = re.sub(r"storeFile file\('[^']*'\)",
                         lambda m: "storeFile file('%s')" % _gradle_sq(kname), content)
        content = re.sub(r"storePassword '[^']*'",
                         lambda m: "storePassword '%s'" % _gradle_sq(KEYSTORE_PASSWORD), content)
        content = re.sub(r"keyAlias '[^']*'",
                         lambda m: "keyAlias '%s'" % _gradle_sq(KEY_ALIAS), content)
        content = re.sub(r"keyPassword '[^']*'",
                         lambda m: "keyPassword '%s'" % _gradle_sq(KEY_PASSWORD), content)
        return content
    _sed_inplace(bgrade, _edit_sign)
    ok('签名证书 -> ' + kname)

    # ---- 步骤 8：更新 AndroidManifest.xml（权限 / 启动主题 / AppKey）----
    log('步骤 8/9: 更新 AndroidManifest.xml...')
    amanifest = os.path.join(res_dir, 'AndroidManifest.xml')

    def _edit_manifest(content):
        if PERMS:
            idx = content.find('<application')
            if idx >= 0:
                content = content[:idx] + '\n'.join(PERMS) + '\n\n' + content[idx:]
        content = content.replace('android:theme="@style/TranslucentTheme"',
                                  'android:theme="@style/SplashTheme"')
        appkey = re.sub(r'([&/\\])', r'\\\1', DCLOUD_APPKEY)
        return re.sub(r'(android:name="dcloud_appkey"[^>]*android:value=")[^"]*(")',
                      lambda mm: mm.group(1) + appkey + mm.group(2), content)
    _sed_inplace(amanifest, _edit_manifest)
    ok('权限 %d 条，dcloud_appkey 已注入' % len(PERMS))

    # ---- 步骤 9：Gradle 编译 ----
    log('步骤 9/9: Gradle 编译...')
    android_home = find_android_home() or '/opt/android-sdk'
    # buildToolsVersion 的引号单双都可能（SDK 5.x 模板用单引号），两种都要能识别，
    # 否则取不到版本号，就不会去补装对应的 build-tools
    bgrade_text = _read_text(bgrade)
    m_cs = re.search(r'compileSdkVersion\s+(\d+)', bgrade_text)
    m_bt = re.search(r'buildToolsVersion\s+["\']([^"\']+)["\']', bgrade_text)
    compile_sdk = m_cs.group(1) if m_cs else None
    build_tools = m_bt.group(1) if m_bt else None

    # 确保对应 platform / build-tools 已安装
    if compile_sdk:
        pkgs = ['platforms;android-%s' % compile_sdk]
        if build_tools:
            pkgs.append('build-tools;%s' % build_tools)
        cmd = 'yes | sdkmanager --sdk_root=%s --install %s' % (
            shlex.quote(android_home), ' '.join(shlex.quote(p) for p in pkgs))
        try:
            subprocess.run(['bash', '-c', cmd], env=os.environ,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)
        except Exception as e:
            warn('sdkmanager 安装失败（若已预装可忽略）: %s' % e)
    try:
        subprocess.run(['bash', '-c', 'yes | sdkmanager --sdk_root=%s --licenses' % shlex.quote(android_home)],
                       env=os.environ, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    except Exception:
        pass

    with open(os.path.join(android_project, 'local.properties'), 'w', encoding='utf-8') as f:
        f.write('sdk.dir=%s\n' % android_home)

    env2 = dict(os.environ, GRADLE_USER_HOME=GRADLE_USER_HOME, ANDROID_HOME=android_home)
    # 不加 --no-daemon：模板 gradle.properties 配置了 org.gradle.jvmargs，
    # --no-daemon 会触发 fork 单次 Daemon 并打印相关提示；用常驻 Daemon 则无此提示，
    # 且后续构建可直接复用 Daemon，速度更快（容器重启后 Daemon 自动消失）
    proc = subprocess.Popen(
        ['bash', gradlew, 'assembleRelease', '--stacktrace', '--console=plain'],
        cwd=android_project, env=env2,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', bufsize=1)
    for line in proc.stdout:
        log(line.rstrip('\n'))
    proc.wait()
    if proc.returncode != 0:
        err('Gradle 编译失败')
        raise RuntimeError('Gradle 编译失败 (exit=%s)' % proc.returncode)

    # ---- 收集 APK ----
    apk_src = os.path.join(simple_demo, 'build', 'outputs', 'apk', 'release', 'simpleDemo-release.apk')
    if not os.path.isfile(apk_src):
        hits = glob.glob(os.path.join(android_project, '**', '*release*.apk'), recursive=True)
        apk_src = hits[0] if hits else None
    if not apk_src:
        err('未找到编译输出的 APK 文件')
        raise RuntimeError('未找到 APK')

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for old_apk in glob.glob(os.path.join(OUTPUT_DIR, '*.apk')):   # 只保留最新一个
        try:
            os.remove(old_apk)
        except Exception:
            pass
    ts = datetime.datetime.now().strftime('%y%m%d%H%M%S')
    apk_name = '%s_%s_%s.apk' % (APP_NAME, VERSION_NAME, ts)
    apk_name = re.sub(r'[/\\"\']', '', apk_name).replace(' ', '')
    shutil.copy2(apk_src, os.path.join(OUTPUT_DIR, apk_name))

    log('')
    log('=' * 42)
    log(' 构建成功!  %s v%s(%s)  %s' % (APP_NAME, VERSION_NAME, VERSION_CODE, APP_PACKAGE))
    log(' APK: output/%s (%s)' % (apk_name, _human_size(os.path.getsize(os.path.join(OUTPUT_DIR, apk_name)))))
    log('=' * 42)
