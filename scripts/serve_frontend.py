"""프론트 파일과 자동차 API 프록시를 같은 포트에서 제공하는 로컬 서버.

python3 scripts/serve_frontend.py --port 8765 --directory frontend
백엔드는 http://127.0.0.1:8003 에서 실행되어 있어야 한다.
"""
import argparse
import http.client
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?", 1)[0].startswith("/api/"):
            self.proxy_api()
        else:
            super().do_GET()

    def proxy_api(self):
        conn = http.client.HTTPConnection("127.0.0.1", 8003, timeout=120)
        try:
            conn.request("GET", self.path, headers={"Accept": "application/json"})
            response = conn.getresponse()
            data = response.read()
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (OSError, http.client.HTTPException):
            self.send_error(502, "Start the API backend on port 8003 first")
        finally:
            conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--directory", default="frontend")
    args = parser.parse_args()
    handler = partial(Handler, directory=str(Path(args.directory).resolve()))
    print(f"Frontend + car API: http://localhost:{args.port}", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
    except KeyboardInterrupt:
        pass
