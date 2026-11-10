"""本地资源服务。

WebView2 通过 ``http://127.0.0.1:<port>`` 取页面位图、图片预览和静态文件。
只绑 loopback，路径里带一次性 token，随窗口一起退出——它不是业务服务端。

为什么不用 data URL 走 JS 桥：一张 150 DPI 的 A4 位图约 400KB，base64 之后
膨胀成 550KB 的 JSON 字符串，一次缩放要重传十几页。走 HTTP 还能吃到浏览器的
图片缓存与异步解码。
"""

from __future__ import annotations

import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from loguru import logger

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

_LONG_CACHE = "private, max-age=31536000, immutable"
_NO_CACHE = "no-store"


class AssetServer:
    """把渲染结果和静态文件喂给 WebView2。

    ``renderer`` 需要有 ``render_page(index, dpi) -> bytes``，
    ``store`` 需要有 ``preview(image_id, max_px) -> bytes`` 与 ``get(image_id) -> bytes``。
    """

    def __init__(self, renderer, store, static_dir: Path) -> None:
        self._renderer = renderer
        self._store = store
        self._static = Path(static_dir).resolve()
        self._token = secrets.token_urlsafe(12)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        handler = _make_handler(self)
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="asset-server", daemon=True
        )
        self._thread.start()
        logger.info("资源服务已启动 {}", self.base_url)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ---- URL ----

    @property
    def token(self) -> str:
        return self._token

    @property
    def base_url(self) -> str:
        port = self._httpd.server_address[1] if self._httpd else 0
        return f"http://127.0.0.1:{port}"

    def _prefix(self) -> str:
        return f"{self.base_url}/a/{self._token}"

    def static_url(self, name: str = "index.html") -> str:
        return f"{self._prefix()}/static/{name}"

    def page_url(self, index: int, dpi: int, version: int = 0) -> str:
        return f"{self._prefix()}/page/{index}.png?dpi={dpi}&v={version}"

    def image_url(self, image_id: str, max_px: int | None = None) -> str:
        suffix = f"?w={max_px}" if max_px else ""
        return f"{self._prefix()}/img/{image_id}{suffix}"

    # ---- 请求处理 ----

    def handle(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        parts = [unquote(part) for part in parsed.path.strip("/").split("/")]
        if len(parts) < 3 or parts[0] != "a" or parts[1] != self._token:
            self._not_found(handler)
            return

        query = parse_qs(parsed.query)
        kind = parts[2]
        try:
            if kind == "page" and len(parts) >= 4:
                self._serve_page(handler, parts[3], query)
            elif kind == "img" and len(parts) >= 4:
                self._serve_image(handler, parts[3], query)
            elif kind == "static" and len(parts) >= 4:
                self._serve_static(handler, "/".join(parts[3:]))
            else:
                self._not_found(handler)
        except Exception:
            logger.exception("资源请求失败 {}", handler.path)
            self._send(handler, b"error", "text/plain; charset=utf-8", _NO_CACHE, 500)

    def _serve_page(self, handler, name: str, query: dict) -> None:
        index = int(name.split(".")[0])
        dpi = int(query.get("dpi", ["150"])[0])
        data = self._renderer.render_page(index, dpi)
        self._send(handler, data, "image/png", _LONG_CACHE)

    def _serve_image(self, handler, image_id: str, query: dict) -> None:
        width = query.get("w")
        if width:
            data = self._store.preview(image_id, int(width[0]))
            mime = "image/jpeg" if not data.startswith(b"\x89PNG") else "image/png"
        else:
            data = self._store.get(image_id)
            mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
        self._send(handler, data, mime, _LONG_CACHE)

    def _serve_static(self, handler, relative: str) -> None:
        target = (self._static / relative).resolve()
        if not target.is_relative_to(self._static) or not target.is_file():
            self._not_found(handler)
            return
        data = target.read_bytes()
        mime = _MIME.get(target.suffix.lower(), "application/octet-stream")
        self._send(handler, data, mime, _NO_CACHE)

    @staticmethod
    def _send(handler, data: bytes, mime: str, cache: str, status: int = 200) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(len(data)))
        handler.send_header("Cache-Control", cache)
        handler.end_headers()
        try:
            handler.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError):
            # 用户滚动太快，浏览器主动断开，不是错误。
            pass

    def _not_found(self, handler) -> None:
        self._send(handler, b"not found", "text/plain; charset=utf-8", _NO_CACHE, 404)


def _make_handler(server: AssetServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PdfImageEditor"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - 基类要求这个名字
            server.handle(self)

        def log_message(self, *args) -> None:
            return

    return Handler
