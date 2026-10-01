"""
Nubra static-IP router (runs on your PC, standard Python only).

OpenAlgo sends all its web traffic to this router (127.0.0.1:8899).
- Sites matching PROXY_DOMAINS (default: nubra.io) go through your static IP proxy.
- Everything else (Telegram, GitHub, market data sites...) goes out on your normal internet.

Settings come from environment variables set by start-openalgo.bat:
  UP_HOST, UP_PORT, UP_USER, UP_PASS   - static IP proxy details
  PROXY_DOMAINS                        - comma list, e.g. "nubra.io"
  DIRECT_DOMAINS                       - exceptions that go direct even if they match PROXY_DOMAINS
  ROUTER_PORT                          - default 8899
"""
import asyncio
import base64
import ssl
import os
import sys
from datetime import datetime

UP_HOST = os.environ.get("UP_HOST", "")
UP_PORT = int(os.environ.get("UP_PORT", "443") or 443)
UP_SCHEME = os.environ.get("UP_SCHEME", "https").lower()   # https = TLS to the proxy (what staticip.in needs)
UP_USER = os.environ.get("UP_USER", "")
UP_PASS = os.environ.get("UP_PASS", "")
DOMAINS = [d.strip().lower().lstrip(".") for d in os.environ.get("PROXY_DOMAINS", "nubra.io").split(",") if d.strip()]
EXCEPT = [d.strip().lower().lstrip(".") for d in os.environ.get("DIRECT_DOMAINS", "").split(",") if d.strip()]
PORT = int(os.environ.get("ROUTER_PORT", "8899") or 8899)
from urllib.parse import unquote
AUTH = base64.b64encode(f"{unquote(UP_USER)}:{unquote(UP_PASS)}".encode()).decode() if UP_USER else ""


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def via_static(host):
    host = host.lower().strip("[]")
    if any(host == d or host.endswith("." + d) for d in EXCEPT):
        return False
    return any(host == d or host.endswith("." + d) for d in DOMAINS)


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def read_head(reader):
    head = await reader.readuntil(b"\r\n\r\n")
    return head.decode("latin-1")


async def open_via_upstream(host, port):
    if UP_SCHEME == "https":
        ctx = ssl.create_default_context()
        r, w = await asyncio.wait_for(asyncio.open_connection(UP_HOST, UP_PORT, ssl=ctx, server_hostname=UP_HOST), 15)
    else:
        r, w = await asyncio.wait_for(asyncio.open_connection(UP_HOST, UP_PORT), 15)
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if AUTH:
        req += f"Proxy-Authorization: Basic {AUTH}\r\n"
    req += "\r\n"
    w.write(req.encode())
    await w.drain()
    head = await asyncio.wait_for(read_head(r), 20)
    status = head.split("\r\n", 1)[0]
    if " 200" not in status:
        w.close()
        raise ConnectionError(f"static IP proxy said: {status}")
    return r, w


async def handle(creader, cwriter):
    try:
        head = await asyncio.wait_for(read_head(creader), 30)
    except Exception:
        cwriter.close()
        return
    first = head.split("\r\n", 1)[0]
    parts = first.split(" ")
    if len(parts) < 3:
        cwriter.close()
        return
    method, target = parts[0].upper(), parts[1]

    if method == "CONNECT":
        host, _, port = target.rpartition(":")
        port = int(port or 443)
        rest = b""
    else:
        # plain http://host[:port]/path request
        from urllib.parse import urlsplit
        u = urlsplit(target)
        host, port = u.hostname or "", u.port or 80
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        lines = head.split("\r\n")
        lines[0] = f"{method} {path} {parts[2]}"
        lines = [l for l in lines if not l.lower().startswith("proxy-")]
        rest = "\r\n".join(lines).encode("latin-1")

    static = via_static(host)
    route = "STATIC IP" if static else "direct"
    try:
        if static:
            sreader, swriter = await open_via_upstream(host, port)
        else:
            sreader, swriter = await asyncio.wait_for(asyncio.open_connection(host, port), 15)
    except Exception as e:
        log(f"FAIL {route:9} {host}:{port} - {e}")
        if static:
            log(f"     -> the static IP proxy cannot reach {host}. If this host is not used to place orders,"
                f" add it to DIRECT_DOMAINS in start-openalgo.bat; otherwise ask staticip.in to allow it.")
        msg = "502 Bad Gateway" if not static else "502 Static IP proxy error"
        try:
            cwriter.write(f"HTTP/1.1 {msg}\r\nContent-Length: 0\r\n\r\n".encode())
            await cwriter.drain()
        finally:
            cwriter.close()
        return

    log(f"{route:9} {host}:{port}")
    if method == "CONNECT":
        cwriter.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await cwriter.drain()
    else:
        swriter.write(rest)
        await swriter.drain()
    await asyncio.gather(pipe(creader, swriter), pipe(sreader, cwriter))


async def main():
    if not UP_HOST:
        log("UP_HOST not set - start this from start-openalgo.bat")
        sys.exit(1)
    server = await asyncio.start_server(handle, "127.0.0.1", PORT)
    log(f"Router on 127.0.0.1:{PORT} -> {UP_SCHEME}://{UP_HOST}:{UP_PORT}. Via static IP: {', '.join(DOMAINS)}. Exceptions (direct): {', '.join(EXCEPT) or 'none'}. Everything else: direct.")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass