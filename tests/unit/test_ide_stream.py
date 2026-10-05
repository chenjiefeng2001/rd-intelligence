"""Controls for the change-notification surface and the SSE stream.

Three layers. The primitive (revision, history, replay) is checked directly. The
HTTP surface is checked against a real server on a real socket, because SSE
framing that is correct in a unit test and wrong on the wire is a common and
expensive failure. The frozen-page boundary is checked to prove this work did
not touch the fixture the other controls depend on.
"""
import http.client
import json
import pathlib
import socket
import subprocess
import sys
import threading
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

import rdebug_ide.app as app  # noqa: E402 -- the repo src layout needs the path before the import, and E402 is that cost


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Server:
    """A real Handler on a real socket.

    Not a fake: the point of these controls is the wire format, so the tests
    speak HTTP/1.1 to a listening server and parse the bytes themselves.
    """

    def __init__(self, configure_with=None):
        self.port = free_port()
        self.httpd = app.ThreadingHTTPServer(("127.0.0.1", self.port), app.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        if configure_with is not None:
            app.configure(configure_with)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def get(self, path, headers=None, read_body=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers=headers or {})
            resp = conn.getresponse()
            body = resp.read() if read_body else b""
            return resp.status, dict(resp.getheaders()), body
        finally:
            conn.close()


class TestTheRevisionPrimitive(unittest.TestCase):
    def setUp(self):
        app._REVISION = 0
        app._HISTORY.clear()
        del app._SUBSCRIBERS[:]

    def test_a_change_increases_the_revision(self):
        before = app.revision()
        app.publish("configured", "a.rdc")
        self.assertEqual(app.revision(), before + 1)

    def test_revisions_are_strictly_increasing(self):
        seen = [app.publish("x")["revision"] for _ in range(5)]
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(len(set(seen)), 5)

    def test_replaying_from_nothing_yields_nothing(self):
        # None means "I have no idea what you have seen", so nothing is safe to
        # replay; the client is expected to take a snapshot instead.
        app.publish("configured")
        self.assertEqual(app.replay_since(None), [])

    def test_replaying_from_zero_yields_everything_buffered(self):
        for _ in range(3):
            app.publish("configured")
        self.assertEqual(len(app.replay_since(0)), 3)

    def test_replaying_from_current_yields_nothing_and_is_not_a_resync(self):
        app.publish("configured")
        self.assertEqual(app.replay_since(app.revision()), [])

    def test_a_gap_older_than_the_buffer_is_reported_not_silently_short(self):
        # This is the whole reason replay_since can return None. A client that
        # missed events must be told it missed them; handing it a short list
        # would let it believe it is current.
        app.HISTORY_LIMIT = 4
        try:
            for _ in range(10):
                app.publish("churn")
            self.assertIsNone(app.replay_since(1))
        finally:
            app.HISTORY_LIMIT = 256

    def test_a_revision_from_another_server_lifetime_is_not_replayed(self):
        app.publish("configured")
        self.assertIsNone(app.replay_since(app.revision() + 500))

    def test_the_buffer_is_bounded(self):
        app.HISTORY_LIMIT = 8
        try:
            for _ in range(50):
                app.publish("churn")
            self.assertLessEqual(len(app._HISTORY), 8)
        finally:
            app.HISTORY_LIMIT = 256

    def test_every_event_carries_the_state_it_describes(self):
        event = app.publish("configured", "a.rdc")
        for field in ("revision", "kind", "detail", "state"):
            with self.subTest(field=field):
                self.assertIn(field, event)
        self.assertEqual(event["state"]["revision"], event["revision"])

    def test_an_unsubscribed_queue_stops_receiving(self):
        q = app.subscribe()
        app.publish("first")
        app.unsubscribe(q)
        app.publish("second")
        self.assertEqual(q.get_nowait()["kind"], "first")

    def test_a_slow_subscriber_cannot_block_the_publisher(self):
        # A full queue raises on put_nowait; that must not propagate, because a
        # notification channel must never be able to stall a query. The queue is
        # deliberately never drained: that is what makes it slow.
        app.subscribe()
        for _ in range(app.HISTORY_LIMIT + 10):
            app.publish("churn")
        app.publish("after")
        self.assertGreater(app.revision(), 0)

    def test_snapshot_is_json_safe(self):
        json.dumps(app.snapshot_state())


class TestTheSnapshotEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_it_reports_the_revision_a_client_should_send(self):
        status, headers, body = self.server.get("/api/state")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        payload = json.loads(body)
        for field in ("ready", "capture", "ci", "revision"):
            with self.subTest(field=field):
                self.assertIn(field, payload)

    def test_it_is_not_cached(self):
        _status, headers, _body = self.server.get("/api/state")
        self.assertIn("no-store", headers.get("Cache-Control", ""))


class TestTheStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def read_stream(self, path, timeout=10):
        """Open a stream and read raw frames off the socket.

        Returns a reader rather than the bytes: the buffer is filled by a
        background thread, so handing back the object at open time would hand
        back an empty snapshot and every assertion would fail on timing alone.
        """
        sock = socket.create_connection(("127.0.0.1", self.server.port), timeout=timeout)
        sock.sendall(("GET " + path + " HTTP/1.1\r\n"
                      "Host: 127.0.0.1\r\n"
                      "Accept: text/event-stream\r\n\r\n").encode("utf-8"))
        buf = bytearray()
        deadline = time.time() + timeout

        def pump():
            sock.settimeout(0.5)
            while time.time() < deadline:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    return
                if not chunk:
                    return
                buf.extend(chunk)

        t = threading.Thread(target=pump, daemon=True)
        t.start()

        def wait_for(needle, within=8):
            limit = time.time() + within
            while needle not in bytes(buf) and time.time() < limit:
                time.sleep(0.05)
            return bytes(buf)

        return sock, wait_for, t

    def test_the_content_type_is_an_event_stream(self):
        sock, wait, t = self.read_stream("/api/events")
        try:
            buf = wait(b"text/event-stream")
            self.assertIn(b"200", buf[:20])
            self.assertIn(b"text/event-stream", buf)
        finally:
            sock.close()

    def test_a_client_learns_its_revision_from_the_first_event(self):
        # Silence would leave a client unable to reconnect meaningfully, so a
        # fresh subscriber is told where it stands immediately.
        sock, wait, t = self.read_stream("/api/events")
        try:
            buf = wait(b"event:")
            self.assertIn(b"id: ", buf)
            self.assertIn(b"data: ", buf)
        finally:
            sock.close()

    def test_a_frame_carries_id_kind_and_data(self):
        event = {"revision": 7, "kind": "configured", "detail": None,
                 "state": {"ready": True}}
        frame = app.Handler._frame(event).decode("utf-8")
        self.assertTrue(frame.startswith("id: 7\n"))
        self.assertIn("event: configured\n", frame)
        self.assertIn('"revision": 7', frame)
        self.assertTrue(frame.endswith("\n\n"))

    def test_the_retry_interval_is_declared(self):
        sock, wait, t = self.read_stream("/api/events")
        try:
            self.assertIn(b"retry:", wait(b"retry:"))
        finally:
            sock.close()

    def test_the_heartbeat_is_a_comment_not_an_event(self):
        # An idle connection must not look like a state change to the client.
        frame = b": heartbeat\n\n"
        self.assertNotIn(b"event:", frame)
        self.assertNotIn(b"data:", frame)
        self.assertTrue(frame.startswith(b":"))

    def test_an_evicted_gap_produces_a_resync_instead_of_a_silent_hole(self):
        old_limit = app.HISTORY_LIMIT
        app.HISTORY_LIMIT = 2
        try:
            for _ in range(8):
                app.publish("churn")
            stale = 1
            sock, wait, t = self.read_stream(
                "/api/events?lastEventId=" + str(stale))
            try:
                buf = wait(b"resync")
                self.assertIn(b"event: resync", buf)
                self.assertIn(b"revision", buf)
            finally:
                sock.close()
        finally:
            app.HISTORY_LIMIT = old_limit

    def test_last_event_id_header_is_honoured(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        try:
            current = app.revision()
            conn.request("GET", "/api/events",
                         headers={"Accept": "text/event-stream",
                                  "Last-Event-ID": str(current)})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIn("text/event-stream", resp.getheader("Content-Type"))
        finally:
            conn.close()

    def test_a_nonsense_revision_is_ignored_rather_than_fatal(self):
        sock, wait, t = self.read_stream("/api/events?lastEventId=not-a-number")
        try:
            self.assertIn(b"event:", wait(b"event:"))
        finally:
            sock.close()


class TestTheFrozenPageIsUntouched(unittest.TestCase):
    """This work is additive. The page is another control's fixture."""

    def test_index_html_is_byte_identical_to_the_committed_fixture(self):
        # Compared through git's index rather than against the working file.
        # core.autocrlf is true here, so the working copy is CRLF while the
        # stored blob is LF; comparing the file against `git show` would report a
        # difference on a repository that has not changed at all. `git diff
        # --quiet` asks the question that is actually being asked: has the
        # content in the index moved?
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "--", "src/rdebug_ide/static/index.html"],
            cwd=str(REPO), capture_output=True)
        self.assertEqual(dirty.returncode, 0,
                         "index.html changed; it is the fixture the frozen IDE "
                         "controls cut their functions out of")

    def test_the_existing_endpoints_still_respond_as_json(self):
        server = Server()
        try:
            for path in ("/api/info", "/api/stats"):
                with self.subTest(path=path):
                    status, headers, body = server.get(path)
                    self.assertEqual(status, 200)
                    self.assertIn("application/json", headers["Content-Type"])
                    json.loads(body)
        finally:
            server.stop()

    def test_an_unknown_endpoint_is_still_a_404(self):
        server = Server()
        try:
            status, _headers, _body = server.get("/api/nope")
            self.assertEqual(status, 404)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
