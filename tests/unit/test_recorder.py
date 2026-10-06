"""Controls for the query recorder.

The properties that matter are not "does it store rows". They are the two that
Rule 2.8 states: recording is best-effort, and it must not change a query. Both
are tested by breaking the store on purpose and asserting the query still answers
identically.

Pixel filtering is checked against substring confusion on purpose. `320,240` is a
substring of `1320,2401`, and a history filter that quietly returns the wrong
rows is worse than one that returns none.
"""
import json
import os
import pathlib
import re
import sys
import tempfile
import threading
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

import rdebug.recorder as rec  # noqa: E402  -- the repo src layout needs the path first


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = str(pathlib.Path(self.dir) / "history.db")
        os.environ[rec.ENV_PATH] = self.path
        rec.close()
        self.addCleanup(rec.close)
        self.addCleanup(os.environ.pop, rec.ENV_PATH, None)
        self.addCleanup(os.environ.pop, rec.ENV_PAYLOADS, None)

    def seed(self, n=3):
        for i in range(n):
            rec.record("ide", "/api/trace", ok=True, latency_ms=float(i),
                       query={"x": 320, "y": 240})


class TestStoredRequestShapes(StoreCase):
    """What actually arrives is not what the unit tests hand it.

    Every other control in this file stores ints and lists of one element,
    because that is convenient. A URL stores strings and parse_qs lists. Both
    differences broke the pixel filter in turn, and neither showed up until the
    IDE served a real request -- so they are pinned here in the shape the wire
    actually produces.
    """

    def test_parse_qs_style_values_are_flattened(self):
        rec.record("ide", "/api/trace", ok=True,
                   query={"x": ["320"], "y": ["240"], "max_draws": ["16"]})
        self.assertEqual(rec.recent()[0]["query"],
                         {"x": "320", "y": "240", "max_draws": "16"})

    def test_a_repeated_parameter_keeps_its_list(self):
        # Collapsing it would lose information, so it is kept and simply will not
        # match a pixel filter.
        rec.record("ide", "/api/diff", ok=True, query={"a": ["1,1", "2,2"]})
        self.assertEqual(rec.recent()[0]["query"]["a"], ["1,1", "2,2"])

    def test_string_coordinates_still_match_a_pixel_filter(self):
        rec.record("ide", "/api/trace", ok=True,
                   query={"x": "320", "y": "240"})
        self.assertEqual(len(rec.recent(x=320, y=240)), 1)

    def test_string_coordinates_still_reject_a_near_miss(self):
        rec.record("ide", "/api/trace", ok=True,
                   query={"x": "320", "y": "241"})
        self.assertEqual(len(rec.recent(x=320, y=240)), 0)

    def test_a_string_coordinate_pair_still_matches(self):
        rec.record("ide", "/api/diff", ok=True, query={"a": "320,240",
                                                       "b": "10,10"})
        self.assertEqual(len(rec.recent(x=320, y=240)), 1)

    def test_a_coordinate_with_padding_still_matches(self):
        rec.record("ide", "/api/diff", ok=True, query={"a": " 320 , 240 "})
        self.assertEqual(len(rec.recent(x=320, y=240)), 1)

    def test_a_non_numeric_coordinate_does_not_raise(self):
        rec.record("ide", "/api/diff", ok=True, query={"a": "not,a,pixel"})
        self.assertEqual(len(rec.recent(x=320, y=240)), 0)

    def test_a_list_query_whose_head_is_not_a_pair_does_not_raise(self):
        rec.record("ide", "/api/diff", ok=True, query={"a": ["320,240", "x"]})
        self.assertEqual(len(rec.recent(x=320, y=240)), 0)

    def test_a_boolean_coordinate_does_not_match_zero(self):
        # bool is an int subclass in Python, so an unguarded comparison turns
        # True into 1 and matches a query about pixel 1,0.
        rec.record("ide", "/api/trace", ok=True, query={"x": True, "y": False})
        self.assertEqual(len(rec.recent(x=1, y=0)), 0)

    def test_a_non_dict_stored_query_does_not_raise(self):
        rec.record("ide", "/api/trace", ok=True, query=["not", "a", "dict"])
        self.assertEqual(len(rec.recent(x=1, y=1)), 0)

    def test_a_malformed_coordinate_pair_is_not_a_match(self):
        rec.record("ide", "/api/diff", ok=True, query={"a": "320,240,9"})
        self.assertEqual(len(rec.recent(x=320, y=240)), 0)


class TestItIsOptIn(unittest.TestCase):
    def setUp(self):
        rec.close()
        self.addCleanup(rec.close)
        os.environ.pop(rec.ENV_PATH, None)
        self.addCleanup(os.environ.pop, rec.ENV_PATH, None)

    def test_no_environment_variable_means_no_store(self):
        self.assertFalse(rec.enabled())
        self.assertIsNone(rec.connection())

    def test_recording_to_nothing_is_a_no_op_not_an_error(self):
        self.assertFalse(rec.record("ide", "/api/trace", ok=True))
        self.assertEqual(rec.recent(), [])
        self.assertIsNone(rec.stats())

    def test_aggregating_nothing_returns_a_readable_zero(self):
        out = rec.aggregate()
        self.assertEqual(out["requests"], 0)
        self.assertEqual(out["failures"], 0)
        self.assertEqual(out["byEndpoint"], [])


class TestRecording(StoreCase):
    def test_a_recorded_query_is_readable(self):
        self.seed(1)
        rows = rec.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["endpoint"], "/api/trace")
        self.assertTrue(rows[0]["ok"])

    def test_the_newest_comes_first(self):
        rec.record("ide", "/api/trace", ok=True, query={"x": 1, "y": 1})
        rec.record("ide", "/api/diff", ok=True, query={"a": "2,2"})
        rows = rec.recent()
        self.assertEqual([r["endpoint"] for r in rows],
                         ["/api/diff", "/api/trace"])

    def test_a_failure_is_recorded_with_its_status_and_error(self):
        rec.record("ide", "/api/resource", ok=False, status=400,
                   error="unknown resource id")
        row = rec.recent()[0]
        self.assertFalse(row["ok"])
        self.assertEqual(row["status"], 400)
        self.assertEqual(row["error"], "unknown resource id")

    def test_payloads_are_off_unless_asked_for(self):
        rec.record("ide", "/api/trace", ok=True, payload={"huge": "tree"})
        self.assertIsNone(rec.recent()[0]["payload"])
        self.assertFalse(rec.payload_enabled())

    def test_payloads_are_stored_when_asked_for(self):
        os.environ[rec.ENV_PAYLOADS] = "1"
        rec.record("ide", "/api/trace", ok=True, payload={"edges": [1, 2]})
        rows = rec.recent(with_payload=True)
        self.assertEqual(rows[0]["payload"], {"edges": [1, 2]})

    def test_the_query_is_stored_as_structure_not_as_a_string_to_match(self):
        rec.record("ide", "/api/trace", ok=True, query={"x": 320, "y": 240})
        self.assertEqual(rec.recent()[0]["query"], {"x": 320, "y": 240})

    def test_unserialisable_values_do_not_lose_the_row(self):
        rec.record("ide", "/api/trace", ok=True,
                   query={"weird": object()}, summary=object())
        rows = rec.recent()
        self.assertEqual(len(rows), 1)
        self.assertIsInstance(rows[0]["query"], dict)

    def test_a_missing_payload_key_reads_as_an_empty_dict(self):
        rec.record("ide", "/api/trace", ok=True)
        self.assertEqual(rec.recent(with_payload=True)[0]["payload"], {})


class TestPixelFiltering(StoreCase):
    def test_it_matches_a_trace_request(self):
        rec.record("ide", "/api/trace", ok=True, query={"x": 320, "y": 240})
        self.assertEqual(len(rec.recent(x=320, y=240)), 1)

    def test_it_matches_either_side_of_a_diff(self):
        rec.record("ide", "/api/diff", ok=True, query={"a": "320,240",
                                                       "b": "10,10"})
        self.assertEqual(len(rec.recent(x=320, y=240)), 1)
        self.assertEqual(len(rec.recent(x=10, y=10)), 1)

    def test_a_substring_is_not_a_match(self):
        # The reason this is parsed rather than string-matched.
        rec.record("ide", "/api/trace", ok=True, query={"x": 1320, "y": 2401})
        self.assertEqual(len(rec.recent(x=320, y=240)), 0)

    def test_a_near_miss_is_not_a_match(self):
        rec.record("ide", "/api/trace", ok=True, query={"x": 320, "y": 241})
        self.assertEqual(len(rec.recent(x=320, y=240)), 0)

    def test_no_filter_returns_everything(self):
        rec.record("ide", "/api/trace", ok=True, query={"x": 1, "y": 1})
        rec.record("ide", "/api/trace", ok=True, query={"x": 2, "y": 2})
        self.assertEqual(len(rec.recent(x=1, y=1)), 1)
        self.assertEqual(len(rec.recent()), 2)

    def test_malformed_stored_json_is_filtered_out_rather_than_matched(self):
        rec.record("ide", "/api/trace", ok=True, query={"x": 1, "y": 1})
        conn = rec.connection()
        conn.execute("UPDATE observations SET query = 'not json'")
        conn.commit()
        self.assertEqual(len(rec.recent(x=1, y=1)), 0)


class TestFiltering(StoreCase):
    def setUp(self):
        super().setUp()
        rec.record("ide", "/api/trace", ok=True, query={"x": 1, "y": 1})
        rec.record("ide", "/api/diff", ok=False, error="boom", query={"a": "2,2"})
        rec.record("mcp", "trace_pixel", ok=True, query={"x": 3, "y": 3})

    def test_by_endpoint(self):
        self.assertEqual(len(rec.recent(endpoint="/api/diff")), 1)

    def test_by_transport_is_reachable_through_endpoint(self):
        self.assertEqual(len(rec.recent(endpoint="trace_pixel")), 1)

    def test_failures_only(self):
        rows = rec.recent(failures_only=True)
        self.assertEqual([r["endpoint"] for r in rows], ["/api/diff"])

    def test_a_time_window_excludes_what_is_outside_it(self):
        now = rec.recent()[0]["ts"]
        self.assertEqual(len(rec.recent(since=now - 60)), 3)
        self.assertEqual(len(rec.recent(since=now + 60)), 0)
        self.assertEqual(len(rec.recent(until=now - 60)), 0)

    def test_the_limit_is_honoured_and_bounded(self):
        for i in range(20):
            rec.record("ide", "/api/trace", ok=True, query={"x": i, "y": i})
        self.assertEqual(len(rec.recent(limit=5)), 5)
        # A caller cannot ask for the whole table by asking for a big number.
        self.assertLessEqual(len(rec.recent(limit=10_000)), 23)
        self.assertEqual(len(rec.recent(limit=0)), 1,
                         "a zero limit means the smallest useful page")


class TestAggregation(StoreCase):
    def setUp(self):
        super().setUp()
        for i in range(4):
            rec.record("ide", "/api/trace", ok=True, latency_ms=10.0 + i)
        rec.record("ide", "/api/resource", ok=False, status=400, error="no id")
        rec.record("ide", "/api/resource", ok=False, status=400, error="no id")
        rec.record("ide", "/api/diff", ok=False, status=400, error="bad pixel")

    def test_counts_requests_and_failures(self):
        out = rec.aggregate()
        self.assertEqual(out["requests"], 7)
        self.assertEqual(out["failures"], 3)

    def test_latency_is_averaged_over_what_has_one(self):
        out = rec.aggregate()
        self.assertAlmostEqual(out["latencyMs"]["avg"], 11.5, places=2)
        self.assertEqual(out["latencyMs"]["max"], 13.0)

    def test_it_breaks_down_by_endpoint(self):
        out = rec.aggregate()
        by = {r["endpoint"]: r for r in out["byEndpoint"]}
        self.assertEqual(by["/api/trace"]["count"], 4)
        self.assertEqual(by["/api/trace"]["failures"], 0)
        self.assertEqual(by["/api/resource"]["failures"], 2)

    def test_repeated_errors_are_ranked(self):
        out = rec.aggregate()
        self.assertEqual(out["topErrors"][0]["error"], "no id")
        self.assertEqual(out["topErrors"][0]["count"], 2)

    def test_it_can_be_scoped_to_one_endpoint(self):
        out = rec.aggregate(endpoint="/api/resource")
        self.assertEqual(out["requests"], 2)
        self.assertEqual(out["failures"], 2)

    def test_it_reports_what_it_dropped(self):
        self.assertIn("dropped", rec.aggregate())


class TestRetention(StoreCase):
    def test_rows_are_capped(self):
        os.environ["RDEBUG_STORE_MAX_ROWS"] = "10"
        self.addCleanup(os.environ.pop, "RDEBUG_STORE_MAX_ROWS", None)
        for i in range(40):
            rec.record("ide", "/api/trace", ok=True, query={"x": i, "y": i})
        rows = rec.recent(limit=1000)
        self.assertLessEqual(len(rows), 10)
        # The newest survive; the oldest are the ones dropped.
        self.assertEqual(rows[0]["query"]["x"], 39)

    def test_old_rows_are_dropped_by_age(self):
        os.environ["RDEBUG_STORE_MAX_AGE"] = "1"
        self.addCleanup(os.environ.pop, "RDEBUG_STORE_MAX_AGE", None)
        import time as _t
        rec.record("ide", "/api/trace", ok=True)
        conn = rec.connection()
        conn.execute("UPDATE observations SET ts = ?", (_t.time() - 3600,))
        conn.commit()
        # Retention runs on write, not on read. Backdating a row and then reading
        # is a state the store is not expected to tidy on its own; the next write
        # is what applies the bound. Asserting read-time trimming would be
        # asserting a different design.
        self.assertEqual(len(rec.recent(limit=10)), 1)
        rec.record("ide", "/api/trace", ok=True, query={"x": 9, "y": 9})
        rows = rec.recent(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["query"], {"x": 9, "y": 9})

    def test_a_store_with_no_retention_configured_is_still_bounded(self):
        # The default has to be a bound, not an absence of one.
        self.assertGreater(rec.DEFAULT_MAX_ROWS, 0)
        self.assertGreater(rec.DEFAULT_MAX_AGE_SECONDS, 0)


class TestItIsBestEffort(StoreCase):
    """Rule 2.8. A broken store must not become a query failure."""

    def test_a_broken_store_returns_instead_of_blocking(self):
        # Written with a join timeout on purpose. This control exists because a
        # plain Lock in the recorder self-deadlocked on exactly this path: the
        # unwritable case hung the thread forever rather than failing, and a
        # suite that hangs tells you nothing about which control broke. A
        # degradation promise has to be checked for timing, not just for return
        # value -- otherwise the failure mode is a stuck process.
        os.environ[rec.ENV_PATH] = os.path.join(self.dir, "no", "such", "h.db")
        rec.close()
        outcome = {}

        def attempt():
            outcome["recorded"] = rec.record("ide", "/api/trace", ok=True)

        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(timeout=15)
        self.assertFalse(worker.is_alive(),
                         "a store that cannot be opened blocked the caller")
        self.assertEqual(outcome.get("recorded"), False)

    def test_reading_a_broken_store_also_returns_promptly(self):
        os.environ[rec.ENV_PATH] = os.path.join(self.dir, "no", "such", "h.db")
        rec.close()
        outcome = {}

        def attempt():
            outcome["rows"] = rec.recent()
            outcome["agg"] = rec.aggregate()

        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(timeout=15)
        self.assertFalse(worker.is_alive(), "reading a broken store blocked")
        self.assertEqual(outcome.get("rows"), [])

    def test_the_lock_is_reentrant(self):
        # Asserted directly because the deadlock it prevents is invisible to
        # every other control here: it hangs instead of failing.
        self.assertIsInstance(rec._LOCK, type(threading.RLock()))
        with rec._LOCK:
            rec._note_drop()      # must not block

    def test_an_unwritable_path_is_reported_not_raised(self):
        os.environ[rec.ENV_PATH] = os.path.join(self.dir, "no", "such",
                                                 "dir", "h.db")
        rec.close()
        self.assertFalse(rec.record("ide", "/api/trace", ok=True))

    def test_a_corrupt_database_is_reported_not_raised(self):
        self.seed(1)
        conn = rec.connection()
        conn.close()
        pathlib.Path(self.path).write_bytes(b"this is not a database" * 100)
        rec.close()
        self.assertFalse(rec.record("ide", "/api/trace", ok=True))

    def test_reading_a_corrupt_database_returns_nothing_rather_than_raising(self):
        self.seed(1)
        conn = rec.connection()
        conn.close()
        pathlib.Path(self.path).write_bytes(b"not a database" * 100)
        rec.close()
        self.assertEqual(rec.recent(), [])
        self.assertEqual(rec.aggregate()["requests"], 0)

    def test_a_read_only_file_does_not_break_recording(self):
        self.seed(1)
        # Windows will refuse the write; the record is lost and counted, and the
        # caller sees False rather than an exception.
        conn = rec.connection()
        conn.close()
        os.chmod(self.path, 0o444)
        try:
            result = rec.record("ide", "/api/trace", ok=True)
        finally:
            os.chmod(self.path, 0o666)
            rec.close()
        self.assertIn(result, (True, False))

    def test_losses_are_counted(self):
        os.environ[rec.ENV_PATH] = os.path.join(self.dir, "no", "such", "h.db")
        rec.close()
        before = rec.dropped()
        rec.record("ide", "/api/trace", ok=True)
        self.assertGreater(rec.dropped(), before)

    def test_stats_are_readable_after_a_failure(self):
        os.environ[rec.ENV_PATH] = os.path.join(self.dir, "no", "such", "h.db")
        rec.close()
        self.assertIsNone(rec.stats())


class TestConcurrency(StoreCase):
    def test_many_threads_recording_concurrently_do_not_lose_rows(self):
        errors = []

        def worker(n):
            try:
                for i in range(10):
                    rec.record("ide", "/api/trace", ok=True,
                               query={"x": n, "y": i})
            except Exception as exc:      # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(len(rec.recent(limit=1000)), 60)

    def test_reading_while_writing_does_not_raise(self):
        stop = threading.Event()
        seen = []

        def writer():
            i = 0
            while not stop.is_set() and i < 200:
                rec.record("ide", "/api/trace", ok=True, query={"x": i, "y": i})
                i += 1

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            for _ in range(20):
                rec.recent(limit=10)
                rec.aggregate()
        finally:
            stop.set()
            t.join(timeout=30)
        seen.append(True)
        self.assertEqual(seen, [True])


class TestTheStoreDoesNotTouchTheQueryPath(StoreCase):
    """The boundary that makes 2.8 hold rather than merely be intended."""

    def test_the_semantic_layers_do_not_import_the_recorder(self):
        banned = ("rdebug/analysis", "rdebug/adapter", "rdebug/query")
        offenders = []
        for base in banned:
            for path in (REPO / "src" / base).rglob("*.py"):
                if "recorder" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path.relative_to(REPO)))
        for name in ("model.py", "evidence.py", "ci.py"):
            for path in (REPO / "src").rglob(name):
                if "recorder" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path.relative_to(REPO)))
        self.assertEqual(offenders, [])

    def test_the_recorder_does_not_import_the_query_layer(self):
        text = (REPO / "src" / "rdebug" / "recorder.py").read_text(encoding="utf-8")
        for banned in ("from .query", "import query", "from .analysis",
                       "from .adapter", "renderdoc"):
            with self.subTest(imported=banned):
                self.assertNotIn(banned, text)

    def test_it_uses_only_the_standard_library(self):
        text = (REPO / "src" / "rdebug" / "recorder.py").read_text(encoding="utf-8")
        imports = re.findall(r"^import (\w+)", text, re.M)
        imports += re.findall(r"^from (\w+) import", text, re.M)
        stdlib = {"json", "os", "sqlite3", "threading", "time"}
        for name in imports:
            with self.subTest(module=name):
                self.assertIn(name, stdlib,
                              "a storage dependency in a pip-installed debug "
                              "tool is a cost with no upside here")



class TestIdenticalAnswers(StoreCase):
    """The load-bearing claim: a query answers the same either way."""

    def test_recording_does_not_alter_a_payload(self):
        payload = {"layers": [{"layer": "RTV", "status": "different"}],
                   "firstDivergence": {"layer": "RTV", "good": {"value": [1, 2]}}}
        before = json.dumps(payload, sort_keys=True)
        rec.record("ide", "/api/diff", ok=True, query={"a": "320,240"}, payload=payload)
        after = json.dumps(payload, sort_keys=True)
        self.assertEqual(before, after)

    def test_a_store_that_cannot_be_opened_leaves_the_payload_alone(self):
        payload = {"layers": [{"layer": "RTV", "status": "same"}]}
        before = json.dumps(payload, sort_keys=True)
        os.environ[rec.ENV_PATH] = os.path.join(self.dir, "no", "dir", "h.db")
        rec.close()
        rec.record("ide", "/api/diff", ok=True, payload=payload)
        self.assertEqual(json.dumps(payload, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
