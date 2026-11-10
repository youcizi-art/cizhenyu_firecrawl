#!/usr/bin/env python3
"""Firecrawl Cloud MCP（零依赖 stdio JSON-RPC）。

API Key 由词真语 Deploy 注入：
  - 进程环境 FIRECRAWL_API_KEY（优先）
  - 或 CIZHENYU_AUTH_DIR/firecrawl.json 的 apiKey
禁止在代码或仓库中写入密钥。
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

SERVER_NAME = "firecrawl"
SERVER_VERSION = "1.0.0"
API_BASE = os.environ.get("FIRECRAWL_API_BASE", "https://api.firecrawl.dev").rstrip("/")


class FirecrawlError(RuntimeError):
    pass


def auth_dir() -> Path | None:
    for key in ("CIZHENYU_AUTH_DIR", "SEOGEO_AUTH_DIR"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw)
    return None


def api_key() -> str:
    env = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if env:
        return env
    base = auth_dir()
    if not base:
        raise FirecrawlError("未设置 FIRECRAWL_API_KEY / CIZHENYU_AUTH_DIR")
    path = base / "firecrawl.json"
    if not path.is_file():
        raise FirecrawlError(f"找不到 Firecrawl 凭据：{path}")
    conf = json.loads(path.read_text(encoding="utf-8-sig"))
    key = (conf.get("apiKey") or conf.get("api_key") or "").strip()
    if not key:
        raise FirecrawlError("firecrawl.json 缺少 apiKey")
    return key


def _request(method: str, path: str, body: dict | None = None, timeout: int = 180) -> dict:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise FirecrawlError(f"HTTP {exc.code}: {detail}") from exc


def scrape(url: str, formats: list[str] | None = None, only_main_content: bool = True) -> dict:
    payload = {
        "url": url,
        "formats": formats or ["markdown"],
        "onlyMainContent": bool(only_main_content),
    }
    return _request("POST", "/v1/scrape", payload)


def crawl_start(url: str, limit: int = 10) -> dict:
    return _request("POST", "/v1/crawl", {"url": url, "limit": min(int(limit or 10), 100)})


def crawl_status(job_id: str) -> dict:
    return _request("GET", f"/v1/crawl/{job_id}")


def map_site(url: str, limit: int = 100) -> dict:
    return _request("POST", "/v1/map", {"url": url, "limit": min(int(limit or 100), 5000)})


def search(query: str, limit: int = 5) -> dict:
    return _request("POST", "/v1/search", {"query": query, "limit": min(int(limit or 5), 20)})


TOOLS = {
    "firecrawl_scrape": {
        "fn": scrape,
        "desc": "用 Firecrawl 抓取单个 URL，返回 Markdown/HTML 等内容。",
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "formats": {"type": "array", "items": {"type": "string"}, "default": ["markdown"]},
                "only_main_content": {"type": "boolean", "default": True},
            },
            "required": ["url"],
        },
    },
    "firecrawl_crawl_start": {
        "fn": crawl_start,
        "desc": "启动站点爬取任务，返回 job id；再用 firecrawl_crawl_status 轮询。",
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["url"],
        },
    },
    "firecrawl_crawl_status": {
        "fn": crawl_status,
        "desc": "查询 Firecrawl crawl 任务状态与结果。",
        "schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    "firecrawl_map": {
        "fn": map_site,
        "desc": "发现站点 URL 地图（sitemap-like）。",
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["url"],
        },
    },
    "firecrawl_search": {
        "fn": search,
        "desc": "Firecrawl 网页搜索，返回标题/URL/摘要。",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
}


def call_tool(name: str, args: dict) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        return {"ok": True, "tool": name, "result": spec["fn"](**args)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, msg_id, params = msg.get("method"), msg.get("id"), (msg.get("params") or {})
        if method == "initialize":
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                }
            )
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": [
                            {"name": n, "description": s["desc"], "inputSchema": s["schema"]}
                            for n, s in TOOLS.items()
                        ]
                    },
                }
            )
        elif method == "tools/call":
            result = call_tool(params.get("name", ""), params.get("arguments") or {})
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
                    },
                }
            )
        elif method == "ping":
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif msg_id is not None:
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )


if __name__ == "__main__":
    serve()
