import gzip
import json
import threading
import unittest
from http.client import HTTPConnection

from realtime_oi_dashboard.server import create_dashboard_server


class FakeStateProvider:
    def __init__(self, state):
        self.state = state

    def get_state(self):
        return self.state


class DashboardHttpCacheTests(unittest.TestCase):
    def setUp(self):
        self.oi_payload = {
            "schema_version": 7,
            "rows": [],
            "description": "重複資料" * 500,
        }
        self.signal_payload = {
            "schema_version": 2,
            "bulls": [],
            "bears": [],
            "spikes": [],
        }
        self.server = create_dashboard_server(
            "127.0.0.1",
            0,
            oi_state_provider=FakeStateProvider(self.oi_payload),
            signal_scan_state_provider=FakeStateProvider(self.signal_payload),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, method, path, headers=None):
        connection = HTTPConnection(
            "127.0.0.1",
            self.server.server_address[1],
            timeout=5,
        )
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            body = response.read()
            response_headers = {
                key.lower(): value for key, value in response.getheaders()
            }
            return response.status, response_headers, body
        finally:
            connection.close()

    def test_json_supports_gzip_and_safe_revalidation(self):
        status, headers, body = self.request(
            "GET",
            "/api/oi",
            {"Accept-Encoding": "br, gzip"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["content-encoding"], "gzip")
        self.assertEqual(headers["vary"], "Accept-Encoding")
        self.assertEqual(
            headers["cache-control"],
            "private, no-cache, must-revalidate",
        )
        self.assertTrue(headers["etag"].startswith('W/"'))
        self.assertEqual(int(headers["content-length"]), len(body))
        self.assertEqual(json.loads(gzip.decompress(body)), self.oi_payload)

        conditional_status, conditional_headers, conditional_body = self.request(
            "GET",
            "/api/oi",
            {
                "Accept-Encoding": "gzip",
                "If-None-Match": f'"unrelated", {headers["etag"]}',
            },
        )

        self.assertEqual(conditional_status, 304)
        self.assertEqual(conditional_body, b"")
        self.assertEqual(conditional_headers["etag"], headers["etag"])
        self.assertEqual(conditional_headers["vary"], "Accept-Encoding")
        self.assertEqual(conditional_headers["content-encoding"], "gzip")
        self.assertNotIn("content-length", conditional_headers)

    def test_gzip_quality_zero_uses_identity_representation(self):
        status, headers, body = self.request(
            "GET",
            "/api/oi",
            {"Accept-Encoding": "*;q=1, gzip;q=0"},
        )

        self.assertEqual(status, 200)
        self.assertNotIn("content-encoding", headers)
        self.assertEqual(headers["vary"], "Accept-Encoding")
        self.assertEqual(json.loads(body), self.oi_payload)

    def test_api_head_matches_selected_get_representation(self):
        get_status, get_headers, get_body = self.request(
            "GET",
            "/api/oi",
            {"Accept-Encoding": "gzip"},
        )
        head_status, head_headers, head_body = self.request(
            "HEAD",
            "/api/oi",
            {"Accept-Encoding": "gzip"},
        )

        self.assertEqual((get_status, head_status), (200, 200))
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers["content-encoding"], "gzip")
        self.assertEqual(head_headers["content-length"], str(len(get_body)))
        self.assertEqual(head_headers["etag"], get_headers["etag"])

    def test_api_errors_are_not_cacheable_or_conditionally_suppressed(self):
        self.server.signal_scan_state_provider = None

        status, headers, body = self.request(
            "GET",
            "/api/signal-scan",
            {
                "Accept-Encoding": "gzip",
                "If-None-Match": "*",
            },
        )

        self.assertEqual(status, 503)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["content-encoding"], "gzip")
        self.assertEqual(headers["vary"], "Accept-Encoding")
        self.assertNotIn("etag", headers)
        self.assertEqual(
            json.loads(gzip.decompress(body)),
            {"error": "Signal scan poller unavailable"},
        )

    def test_static_assets_use_etag_cache_and_preserve_head_length(self):
        get_status, get_headers, get_body = self.request(
            "GET",
            "/static/css/dashboard.css",
        )
        head_status, head_headers, head_body = self.request(
            "HEAD",
            "/static/css/dashboard.css",
        )

        self.assertEqual((get_status, head_status), (200, 200))
        self.assertEqual(
            get_headers["cache-control"],
            "public, no-cache, must-revalidate",
        )
        self.assertTrue(get_headers["etag"].startswith('"'))
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers["content-length"], str(len(get_body)))
        self.assertEqual(head_headers["etag"], get_headers["etag"])

        cached_status, cached_headers, cached_body = self.request(
            "GET",
            "/static/css/dashboard.css",
            {"If-None-Match": get_headers["etag"]},
        )
        self.assertEqual(cached_status, 304)
        self.assertEqual(cached_body, b"")
        self.assertEqual(cached_headers["etag"], get_headers["etag"])
        self.assertEqual(
            cached_headers["cache-control"],
            "public, no-cache, must-revalidate",
        )

    def test_index_revalidates_and_errors_remain_no_store(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["cache-control"], "no-cache")

        cached_status, cached_headers, cached_body = self.request(
            "GET",
            "/index.html",
            {"If-None-Match": headers["etag"]},
        )
        self.assertEqual(cached_status, 304)
        self.assertEqual(cached_body, b"")
        self.assertEqual(cached_headers["cache-control"], "no-cache")

        missing_status, missing_headers, _ = self.request("GET", "/missing")
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing_headers["cache-control"], "no-store")
        self.assertEqual(missing_headers["x-content-type-options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
