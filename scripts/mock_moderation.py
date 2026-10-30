"""本地审核服务模拟，用于联调与多实例测试。

用法：
    python scripts/mock_moderation.py --port 8090 --delay 3
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    delay = 0.0
    blocked_words: list[str] = []

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            payload = {}
        text = str(payload.get("text") or "")
        if self.delay:
            time.sleep(self.delay)
        blocked = any(word and word in text for word in self.blocked_words)
        body = json.dumps(
            {
                "blocked": blocked,
                "reason": "命中模拟敏感词" if blocked else "",
                "category": "MOCK",
            },
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--blocked-words", default="")
    args = parser.parse_args()
    Handler.delay = args.delay
    Handler.blocked_words = [word for word in args.blocked_words.split(",") if word]
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
