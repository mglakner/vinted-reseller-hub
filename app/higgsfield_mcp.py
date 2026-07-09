"""Client for the Higgsfield hosted MCP server (mcp.higgsfield.ai) with OAuth.

Used by the image_gen job, and can be run directly:

  python -m app.higgsfield_mcp login     # one-time OAuth (open URL, log in)
  python -m app.higgsfield_mcp tools     # list the server's tools
  python -m app.higgsfield_mcp schema <name>  # print a tool's input schema

Tokens are stored in data/higgsfield_tokens.json and refresh automatically.
The OAuth flow needs a browser once; if the server is headless, run 'login' on
your own machine and copy the token file into the server's data/ directory.
"""
import asyncio
import base64
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from . import config

SERVER_URL = "https://mcp.higgsfield.ai/mcp"
TOKEN_FILE = config.DATA_DIR / "higgsfield_tokens.json"
REDIRECT_PORT = 8399
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


class FileTokenStorage(TokenStorage):
    async def get_tokens(self) -> OAuthToken | None:
        if TOKEN_FILE.exists():
            data = json.loads(TOKEN_FILE.read_text())
            if data.get("tokens"):
                return OAuthToken.model_validate(data["tokens"])
        return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
        data["tokens"] = tokens.model_dump(mode="json")
        TOKEN_FILE.write_text(json.dumps(data, indent=2))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        if TOKEN_FILE.exists():
            data = json.loads(TOKEN_FILE.read_text())
            if data.get("client_info"):
                return OAuthClientInformationFull.model_validate(data["client_info"])
        return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        data = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
        data["client_info"] = client_info.model_dump(mode="json")
        TOKEN_FILE.write_text(json.dumps(data, indent=2))


_auth_code: dict = {}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        code = q.get("code", [None])[0]
        if parsed.path != "/callback" or not code:
            self.send_response(404)
            self.end_headers()
            return
        _auth_code["code"] = code
        _auth_code["state"] = q.get("state", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>Higgsfield connected — you can close this tab.</h2>".encode())

    def log_message(self, *args):
        pass


async def _redirect_handler(auth_url: str) -> None:
    print(f"\nOpen this URL and log in to Higgsfield:\n\n  {auth_url}\n", flush=True)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass


async def _callback_handler() -> tuple[str, str | None]:
    server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    while "code" not in _auth_code:
        await asyncio.sleep(0.5)
    server.shutdown()
    return _auth_code["code"], _auth_code.get("state")


def _provider() -> OAuthClientProvider:
    return OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=OAuthClientMetadata(
            client_name="vinted-hub",
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=FileTokenStorage(),
        redirect_handler=_redirect_handler,
        callback_handler=_callback_handler,
    )


async def _session():
    return streamablehttp_client(SERVER_URL, auth=_provider())


async def list_tools() -> list:
    async with streamablehttp_client(SERVER_URL, auth=_provider()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def call_tool(name: str, arguments: dict):
    async with streamablehttp_client(SERVER_URL, auth=_provider()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)


def download_urls_from_result(result) -> list[str]:
    """Extracts image URLs from a tool result (text JSON or links)."""
    urls: list[str] = []
    for block in result.content:
        if getattr(block, "type", "") == "text":
            text = block.text
            import re
            urls += re.findall(r"https://[^\s\"']+\.(?:png|jpe?g|webp)[^\s\"']*", text)
    return urls


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tools"
    if cmd == "login" or cmd == "tools":
        tools = asyncio.run(list_tools())
        print(f"\nConnected. {len(tools)} tools:")
        for t in tools:
            print(f"  - {t.name}: {(t.description or '')[:100]}")
    elif cmd == "test":
        tools = asyncio.run(list_tools())
        print("Tools:", [t.name for t in tools])
        print("Then call call_tool manually — see a schema with 'schema <name>'.")
    elif cmd == "schema":
        tools = asyncio.run(list_tools())
        for t in tools:
            if t.name == sys.argv[2]:
                print(json.dumps(t.inputSchema, indent=2))
