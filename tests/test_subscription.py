import json
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from proxyfleet.subscription import (
    SubscriptionError,
    build_subscription_status,
    parse_provider_snapshot,
    refresh_subscription_provider,
    load_last_known_good,
    mark_subscription_failure,
    parse_subscription_userinfo,
    update_last_known_good,
    validate_subscription_body,
)


class SubscriptionTests(unittest.TestCase):
    def test_parse_userinfo_header(self):
        parsed = parse_subscription_userinfo("upload=10; download=20; total=100; expire=1893456000")
        self.assertEqual(10, parsed["upload"])
        self.assertEqual(20, parsed["download"])
        self.assertEqual(100, parsed["total"])
        self.assertEqual(1893456000, parsed["expire"])

    def test_missing_userinfo_fields_are_none(self):
        parsed = parse_subscription_userinfo("upload=10")
        self.assertEqual(10, parsed["upload"])
        self.assertIsNone(parsed["download"])
        self.assertIsNone(parsed["total"])
        self.assertIsNone(parsed["expire"])

    def test_invalid_userinfo_integer_fails(self):
        with self.assertRaisesRegex(SubscriptionError, "整数"):
            parse_subscription_userinfo("upload=nope")

    def test_empty_body_fails(self):
        with self.assertRaisesRegex(SubscriptionError, "为空"):
            validate_subscription_body(b"  \n")

    def test_html_body_fails(self):
        with self.assertRaisesRegex(SubscriptionError, "HTML"):
            validate_subscription_body(b"<!doctype html><html></html>")

    def test_build_status_computes_remaining_and_expire(self):
        status = build_subscription_status(
            "airport-main",
            "upload=10; download=20; total=100; expire=1893456000",
            b"provider-body",
        ).to_dict()
        self.assertEqual(70, status["remaining_bytes"])
        self.assertEqual("2030-01-01T00:00:00Z", status["expire_at"])
        self.assertEqual("fresh", status["freshness"])

    def test_update_last_known_good_is_atomic_and_loadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = update_last_known_good(Path(tmp), "airport-main", "upload=1; download=2; total=10", b"valid")
            body, loaded_status = load_last_known_good(Path(tmp), "airport-main")
            self.assertEqual(b"valid", body)
            self.assertEqual(status.content_sha256, loaded_status["content_sha256"])

    def test_failure_does_not_overwrite_last_known_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            update_last_known_good(cache, "airport-main", "upload=1; download=2; total=10", b"valid")
            stale = mark_subscription_failure(cache, "airport-main", "E_SUB_FETCH")
            body, _ = load_last_known_good(cache, "airport-main")
            self.assertEqual(b"valid", body)
            self.assertEqual("stale", stale["freshness"])
            self.assertEqual("E_SUB_FETCH", stale["last_error_code"])

    def test_failure_without_cache_reports_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = mark_subscription_failure(Path(tmp), "airport-main", "E_SUB_FETCH")
            self.assertEqual("unknown", status["freshness"])
            self.assertIsNone(status["download_bytes"])

    def test_status_json_uses_null_for_unknown_values(self):
        status = build_subscription_status("airport-main", None, b"valid").to_dict()
        encoded = json.dumps(status)
        self.assertIn('"download_bytes": null', encoded)

    def test_parse_yaml_provider_snapshot(self):
        parsed = parse_provider_snapshot(
            b"""
proxies:
  - name: jp-01
    type: socks5
    server: 127.0.0.1
    port: 1080
"""
        )
        self.assertEqual("jp-01", parsed["proxies"][0]["name"])

    def test_refresh_provider_writes_lkg_and_failure_does_not_overwrite(self):
        first_body = json.dumps(
            {
                "proxies": [
                    {"name": "jp-01", "type": "socks5", "server": "127.0.0.1", "port": 1080}
                ]
            }
        ).encode("utf-8")
        with _subscription_server(
            [
                (200, first_body, "upload=1; download=2; total=10"),
                (200, b"<html>bad</html>", None),
            ]
        ) as url, tempfile.TemporaryDirectory() as tmp:
            provider, status = refresh_subscription_provider(Path(tmp), "airport-main", url, name_prefix="[A] ")
            self.assertEqual("[A] jp-01", provider["proxies"][0]["name"])
            self.assertEqual("fresh", status.freshness)

            provider, status = refresh_subscription_provider(Path(tmp), "airport-main", url, name_prefix="[A] ")
            self.assertEqual("[A] jp-01", provider["proxies"][0]["name"])
            self.assertEqual("stale", status.freshness)
            body, _ = load_last_known_good(Path(tmp), "airport-main")
            self.assertIn(b"[A] jp-01", body)

class _SubscriptionServer:
    def __init__(self, responses):
        self._responses = list(responses)
        responses_ref = self._responses

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if responses_ref:
                    status, body, userinfo = responses_ref.pop(0)
                else:
                    status, body, userinfo = 500, b"exhausted", None
                self.send_response(status)
                if userinfo is not None:
                    self.send_header("Subscription-Userinfo", userinfo)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A003
                return

        class Server(ThreadingHTTPServer):
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{self._server.server_port}/sub"

    def __enter__(self):
        self._thread.start()
        return self.url

    def __exit__(self, exc_type, exc, tb):
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()


def _subscription_server(responses):
    return _SubscriptionServer(responses)


if __name__ == "__main__":
    unittest.main()
