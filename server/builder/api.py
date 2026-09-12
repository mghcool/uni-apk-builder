#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 接口：路由、SSE 构建流、APK 下载、静态说明页。

路由：
    GET  /               静态说明页（wwwroot/index.html，未命中路径 SPA fallback）
    GET  /api/download   下载最新一次构建成功产出的 APK
    POST /api/build      上传 zip 触发构建，SSE 输出日志；占用中返回 409
"""

import os
import json
import shutil
import tempfile
import threading
import mimetypes
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

from .config import build_lock, WWWROOT, MAX_UPLOAD_BYTES
from .build import build_project, BuildCancelled
from .utils import find_apk, extract_zip, _human_size


class Handler(BaseHTTPRequestHandler):
    server_version = 'uni-app-builder/py'

    def setup(self):
        super().setup()
        # SSE 日志由主线程与心跳线程并发写入同一连接，必须串行化，
        # 否则两次写入可能交错，产生损坏的事件
        self._sse_lock = threading.Lock()
        # 客户端是否已断开（由 SSE 写失败置位）。用于中止正在跑的构建
        self._client_gone = False

    def log_message(self, fmt, *args):
        pass  # 关闭默认访问日志（构建日志已单独输出）

    # ---- 响应辅助 ----
    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_sse(self, line):
        """写一行 SSE 事件并立即刷新（主线程与心跳线程并发调用安全）

        写失败即判定客户端已断开：置位 _client_gone 并跳过后续写入，
        上层据此中止构建，避免 Gradle 白跑几分钟
        """
        if self._client_gone:
            return
        try:
            with self._sse_lock:
                self.wfile.write(('data: ' + line + '\n\n').encode('utf-8'))
                self.wfile.flush()
        except OSError:
            # 含 BrokenPipeError / ConnectionResetError / ConnectionAbortedError
            self._client_gone = True

    def _content_length(self):
        """解析 Content-Length；缺失或非法按 0 处理"""
        try:
            return int(self.headers.get('Content-Length', 0) or 0)
        except ValueError:
            return 0

    def _read_body(self):
        length = self._content_length()
        data = b''
        while len(data) < length:
            chunk = self.rfile.read(length - len(data))
            if not chunk:
                break
            data += chunk
        return data

    def _discard_body(self):
        """读完请求体并丢弃（分块读，不占内存）

        拒绝请求时必须先把 body 读完再回响应：若服务端提前响应并关闭连接，
        客户端还在写 body 时会收到 RST，表现为"连接错误"而非我们回的 409
        """
        remaining = self._content_length()
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    # ---- 静态页面 ----
    def _serve_index(self):
        try:
            with open(os.path.join(WWWROOT, 'index.html'), 'rb') as f:
                body = f.read()
        except Exception:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        """从 wwwroot/ 提供静态文件；未命中返回 index.html（SPA fallback）"""
        full = os.path.normpath(os.path.join(WWWROOT, path.lstrip('/')))
        root = os.path.normpath(WWWROOT)
        if not (full == root or full.startswith(root + os.sep)) \
                or os.path.isdir(full) or not os.path.isfile(full):
            self._serve_index()
            return
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        try:
            with open(full, 'rb') as f:
                body = f.read()
        except Exception:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- 路由 ----
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html'):
            self._serve_index()
        elif path == '/api/download':
            self._download()
        elif not path.startswith('/api'):
            self._serve_static(path)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/build':
            self._build()
        else:
            self.send_error(404)

    # ---- 构建接口 ----
    def _build(self):
        # 上传体积上限：只看 Content-Length，在读取请求体、抢锁、解压之前就拒绝。
        # 放在抢锁前是有意的——超限请求不该排在一个正在跑的构建后面等 409。
        # 与 409 同理，必须先读完请求体再回响应（理由见 _discard_body）
        length = self._content_length()
        if length > MAX_UPLOAD_BYTES:
            self._discard_body()
            self._send_json(413, {
                'error': '上传包过大：%s，上限 %s'
                         % (_human_size(length), _human_size(MAX_UPLOAD_BYTES)),
            })
            return

        # 解析查询参数
        qs = parse_qs(urlparse(self.path).query)

        def q(name):
            v = qs.get(name)
            return v[0].strip() if v else ''

        params = {
            'package': q('package'),
            'ksPwd': q('ksPwd'),
            'ksAlias': q('ksAlias'),
            'appkey': q('appkey'),
        }

        # 并发控制放在读取请求体之前：并发时不必先把几十 MB 的 zip 收下来
        # 再解压到磁盘，抢不到锁直接把请求体读完丢弃（必须先读完再回，
        # 理由见 _discard_body）
        if not build_lock.acquire(blocking=False):
            self._discard_body()
            self._send_json(409, {'error': '已有构建正在执行，请等待当前构建结束后再试'})
            return

        # 抢到锁之后，任何异常/提前返回路径都必须释放锁并清理上传目录
        tmp_dir = None
        try:
            # 读取 zip 请求体
            data = self._read_body()
            if not data:
                self._send_json(400, {'error': '请求体为空，请上传 zip 压缩包'})
                return
            # 上传临时目录放在系统临时目录，与构建工作目录分开，
            # 避免 build_project 开头清空 WORK_DIR 时把上传内容一起删掉
            tmp_dir = tempfile.mkdtemp(prefix='upload_')
            try:
                extract_zip(data, tmp_dir)
            except Exception as e:
                self._send_json(400, {'error': '解压失败: ' + str(e)})
                return

            self._stream_build(tmp_dir, params)
        except Exception as e:
            print('[ERROR] 构建请求处理异常: %s' % e, flush=True)
        finally:
            build_lock.release()
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def _stream_build(self, tmp_dir, params):
        """以 SSE 逐行输出一次构建日志（调用方保证已持有 build_lock）"""
        # SSE 响应头。无 Content-Length，客户端靠连接关闭(EOF)判断流结束，
        # 因此响应结束后必须关闭连接
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

        # 取消事件：客户端断开时置位，传给 build_project 让它尽早终止 Gradle
        cancel = threading.Event()

        # 日志同时输出到控制台（docker logs 排查用）与 SSE
        def log(line):
            print(line, flush=True)
            self._write_sse(line)      # 写失败会置位 _client_gone
            if self._client_gone:
                cancel.set()

        # 心跳：每 30 秒发一个空事件，防止客户端/代理超时断开。
        # 它同时也是断连探针：客户端已走时这次写入会失败并置位 _client_gone，
        # 从而使下一次 log() 立即置位 cancel
        heartbeat_stop = threading.Event()

        def heartbeat():
            while not heartbeat_stop.wait(30):
                self._write_sse('')

        threading.Thread(target=heartbeat, daemon=True).start()

        log('[开始] 构建已启动...')
        try:
            build_project(tmp_dir, params, log, cancel)
            log('=== 构建结束 (exit=0) ===')
        except BuildCancelled as e:
            # 客户端已断开，再发 SSE 没有意义，只留一行控制台日志
            print('[INFO] 构建已中止: %s' % e, flush=True)
        except Exception as e:
            log('构建异常: ' + str(e))
            log('=== 构建结束 (exit=1) ===')
        finally:
            heartbeat_stop.set()

    # ---- 下载接口 ----
    def _download(self):
        apk = find_apk()
        if not apk:
            self._send_json(404, {'error': 'APK 不存在，请先构建'})
            return
        try:
            with open(apk, 'rb') as f:
                body = f.read()
        except Exception as e:
            self._send_json(500, {'error': str(e)})
            return
        fname = os.path.basename(apk)
        ascii_name = fname if fname.isascii() else 'app.apk'
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Disposition',
                         "attachment; filename=\"%s\"; filename*=UTF-8''%s"
                         % (ascii_name, quote(fname)))
        self.end_headers()
        self.wfile.write(body)
