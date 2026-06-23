import json
import tempfile
import unittest
from pathlib import Path

from proxyfleet.subscription import (
    SubscriptionError,
    build_subscription_status,
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


if __name__ == "__main__":
    unittest.main()
