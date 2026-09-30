"""Controls for gate 3, the cold-equals-warm equivalence check.

The real check passes on this environment, on a D3D11 single-draw capture and
on a Vulkan application capture. That makes it easy to believe the check is
doing nothing, so these controls are mostly about the opposite: proving it
fails when it should.

Six reverts are required, and each has a control here:

  equal payloads                     -> PASS
  comparison ignores a real diff     -> must FAIL
  recycle or cross-worker removed    -> must FAIL
  unavailable treated as equal       -> must FAIL
  infrastructure failure as unknown  -> must FAIL
  volatile-field exclusion returns   -> must FAIL

The unit controls drive the comparison and verdict logic directly, so they are
fast and independent of whether a GPU is present. One control runs the real
check end to end, which is the positive control for the state the project is
actually in.

Nothing here asserts anything about a pipeline. Gate 3 being wired or not
wiring is a separate decision, and the release gate spec is not touched by
these controls.
"""

import importlib.util
import json
import os
import unittest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _load():
    spec = importlib.util.spec_from_file_location(
        "cold_warm_gate", os.path.join(REPO_ROOT, "scripts", "cold_warm_gate.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G3 = _load()


def _collection(label, pid, payloads):
    return {
        "label": label,
        "pid": pid,
        "pid_before": pid,
        "cases": {
            cid: ({"status": "ok", "payload": p} if not isinstance(p, dict)
                  or "status" not in p else p)
            for cid, p in payloads.items()
        },
    }


def _ok(value):
    return {"status": "ok", "payload": value}


def _unavailable(kind="QueryError", message="no debug info available"):
    return {"status": "unavailable", "error_type": kind, "error": message}


class TestComparisonIsComplete(unittest.TestCase):
    """The comparison must look at everything, and must not be lazy."""

    def test_equal_payloads_are_pass(self):
        a = _collection("A_cold", 1, {"c": _ok({"a": 1, "b": [1, 2]})})
        b = _collection("A_warm", 1, {"c": _ok({"a": 1, "b": [1, 2]})})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.PASS)

    def test_any_value_difference_is_regression(self):
        a = _collection("A_cold", 1, {"c": _ok({"a": 1, "b": [1, 2]})})
        b = _collection("A_warm", 1, {"c": _ok({"a": 1, "b": [1, 3]})})
        verdict, detail = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)
        self.assertTrue(detail[0]["differing_path_count"])

    def test_deeply_nested_difference_is_found(self):
        a = _collection("A_cold", 1, {"c": _ok({"x": {"y": {"z": [1, {"k": 2}]}}})})
        b = _collection("A_warm", 1, {"c": _ok({"x": {"y": {"z": [1, {"k": 3}]}}})})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)

    def test_added_or_removed_key_is_regression(self):
        a = _collection("A_cold", 1, {"c": _ok({"a": 1})})
        b = _collection("A_warm", 1, {"c": _ok({"a": 1, "extra": 2})})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)

    def test_list_length_difference_is_regression(self):
        a = _collection("A_cold", 1, {"c": _ok({"a": [1, 2]})})
        b = _collection("A_warm", 1, {"c": _ok({"a": [1, 2, 3]})})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)

    def test_key_order_alone_is_not_a_difference(self):
        """Canonicalisation is not a filter.

        Dict construction order is not a semantic fact. If it were compared,
        an unrelated refactor would produce a REGRESSION and the pressure
        would go toward adding exclusions, which is the failure mode this
        contract forbids. Every value is still compared.
        """
        a = _collection("A_cold", 1, {"c": _ok({"a": 1, "b": 2})})
        b = _collection("A_warm", 1, {"c": _ok({"b": 2, "a": 1})})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.PASS)

    def test_canonical_output_keeps_every_value(self):
        payload = {"a": 1, "b": [1, {"c": 2}], "d": None, "e": True}
        text = G3.canonical(payload)
        self.assertEqual(json.loads(text), payload)
        for token in ("1", "2", "null", "true"):
            self.assertIn(token, text)


class TestNoVolatileFieldExclusion(unittest.TestCase):
    """A volatile-field exemption would let nondeterminism back in silently."""

    VOLATILE = {
        "elapsedMs": 12.5,
        "workerPid": 4242,
        "privateMemoryMb": 88.0,
        "rssBytes": 123456,
        "timestamp": "2026-09-29T00:00:00Z",
    }

    def test_volatile_looking_field_that_differs_is_regression(self):
        a = _collection("A_cold", 1, {"c": _ok(dict(self.VOLATILE, stable=1))})
        b = _collection("A_warm", 1, {"c": _ok(dict(self.VOLATILE, stable=1,
                                                      elapsedMs=99.0))})
        verdict, detail = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION,
                         "no field may be exempted from comparison")
        self.assertTrue(any("elapsedMs" in d["path"] for d in
                            detail[0]["differing_paths"]))

    def test_no_exclusion_list_exists_in_the_module(self):
        """Structural guard: a re-introduced exemption list must be visible."""
        source = open(os.path.join(REPO_ROOT, "scripts", "cold_warm_gate.py"),
                      encoding="utf-8").read()
        for banned in ("VOLATILE_FIELDS", "EXCLUDE_FIELDS", "IGNORE_FIELDS",
                       "NORMALISE_FIELDS", "strip_volatile", "pop_volatile"):
            self.assertNotIn(banned, source,
                             f"{banned} would reintroduce a field exemption")


class TestUnavailableIsNotEqual(unittest.TestCase):
    """A case that cannot run is not the same as a case that agrees."""

    def test_both_unavailable_identically_is_unknown(self):
        a = _collection("A_cold", 1, {"c": _unavailable()})
        b = _collection("A_warm", 1, {"c": _unavailable()})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.UNKNOWN)
        self.assertNotEqual(verdict, G3.PASS)

    def test_both_unavailable_differently_is_regression(self):
        a = _collection("A_cold", 1, {"c": _unavailable("QueryError", "a")})
        b = _collection("A_warm", 1, {"c": _unavailable("QueryError", "b")})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)

    def test_both_unavailable_different_type_is_regression(self):
        a = _collection("A_cold", 1, {"c": _unavailable("QueryError", "x")})
        b = _collection("A_warm", 1, {"c": _unavailable("WorkerError", "x")})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)

    def test_available_on_one_side_only_is_regression(self):
        a = _collection("A_cold", 1, {"c": _ok({"a": 1})})
        b = _collection("A_warm", 1, {"c": _unavailable()})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)

    def test_unavailable_then_available_is_regression(self):
        a = _collection("A_cold", 1, {"c": _unavailable()})
        b = _collection("A_warm", 1, {"c": _ok({"a": 1})})
        verdict, _ = G3.compare_case("c", a, [("A_warm", b)])
        self.assertEqual(verdict, G3.REGRESSION)


class TestWorkerBoundaryIsRequired(unittest.TestCase):
    """The boundary is the point; losing it must abort, not pass."""

    class _Mgr:
        """Stands in for WorkerManager with a scripted pid sequence."""

        def __init__(self, pids, inventory=None):
            self.pids = list(pids)
            self.inventory_payload = inventory or {
                "textures": [{"id": "ResourceId::1", "width": 4, "height": 4}],
                "last_event_id": 1,
            }
            self.disposed = 0
            self.queries = 0

        def ping(self, capture):
            return True

        def inventory(self, capture):
            return self.inventory_payload

        def pid(self, capture):
            return self.pids[0] if self.pids else None

        def dispose(self, capture):
            self.disposed += 1
            if len(self.pids) > 1:
                self.pids.pop(0)

        def dispose_all(self):
            pass

        def query(self, capture, tool, **kwargs):
            self.queries += 1
            if kwargs.get("include_shader_values"):
                return {"tool": tool, "sv": True}
            if tool == "debug_pixel":
                return {"tool": tool, "steps": [1, 2, 3]}
            return {"tool": tool, "args": sorted(kwargs.items())}

    def test_same_pid_throughout_aborts(self):
        """No recycle happened, so the gate must not claim equivalence."""
        mgr = self._Mgr(pids=[100])
        with self.assertRaises(G3.GateAbort) as ctx:
            G3.run("x.rdc", warmup=0, mgr=mgr)
        self.assertIn("recycle", str(ctx.exception))

    def test_no_recycle_call_aborts(self):
        mgr = self._Mgr(pids=[100])
        original = mgr.dispose
        mgr.dispose = lambda capture: None
        with self.assertRaises(G3.GateAbort):
            G3.run("x.rdc", warmup=0, mgr=mgr)
        mgr.dispose = original

    def test_real_boundary_runs_and_records_pids(self):
        mgr = self._Mgr(pids=[100, 200])
        verdict = G3.run("x.rdc", warmup=1, mgr=mgr)
        ev = verdict["evidence"]
        self.assertEqual(ev["workers"]["A_cold"], 100)
        self.assertEqual(ev["workers"]["A_warm"], 100)
        self.assertEqual(ev["workers"]["B_cold"], 200)
        self.assertEqual(ev["workers"]["B_warm"], 200)
        self.assertTrue(ev["same_worker_within_A"])
        self.assertTrue(ev["recycle_produced_new_worker"])
        self.assertEqual(verdict["outcome"], G3.PASS)

    def test_evidence_separates_worker_identity_from_payload(self):
        """PIDs are execution evidence and must not be compared as payload."""
        mgr = self._Mgr(pids=[100, 200])
        verdict = G3.run("x.rdc", warmup=0, mgr=mgr)
        text = json.dumps(verdict, default=str)
        self.assertIn("workers", text)
        for _cid, case in verdict["cases"].items():
            for comp in case["comparisons"]:
                for d in comp.get("differing_paths", []):
                    self.assertNotIn("pid", d["path"].lower())

    def test_mandatory_case_count(self):
        mgr = self._Mgr(pids=[100, 200])
        verdict = G3.run("x.rdc", warmup=0, mgr=mgr)
        self.assertEqual(
            sorted(verdict["cases"]),
            ["debug_pixel", "diff_pixel", "diff_pixel_shader_values",
             "trace_pixel", "trace_resource"],
        )
        for cid, case in verdict["cases"].items():
            self.assertTrue(case["mandatory"], cid)

    def test_pairs_are_reported(self):
        mgr = self._Mgr(pids=[100, 200])
        verdict = G3.run("x.rdc", warmup=0, mgr=mgr)
        pairs = verdict["evidence"]["pairs"]
        self.assertTrue(any(p["crossed_recycle"] for p in pairs))
        self.assertTrue(any(p["crossed_worker"] for p in pairs))
        self.assertTrue(any(not p["crossed_recycle"] for p in pairs))


class TestInfrastructureIsNotContent(unittest.TestCase):
    """Environment failure must not be laundered into unknown or pass."""

    class _BadMgr(TestWorkerBoundaryIsRequired._Mgr):
        def ping(self, capture):
            raise RuntimeError("no worker for capture")

    def test_worker_will_not_start_is_infrastructure(self):
        with self.assertRaises(G3.GateAbort) as ctx:
            G3.run("x.rdc", warmup=0, mgr=self._BadMgr(pids=[1]))
        self.assertIn("worker did not start", str(ctx.exception))

    class _NoInventory(TestWorkerBoundaryIsRequired._Mgr):
        def inventory(self, capture):
            raise RuntimeError("capture unreadable")

    def test_inventory_failure_is_infrastructure(self):
        with self.assertRaises(G3.GateAbort):
            G3.run("x.rdc", warmup=0, mgr=self._NoInventory(pids=[1]))

    class _NoTextures(TestWorkerBoundaryIsRequired._Mgr):
        def inventory(self, capture):
            return {"textures": [], "last_event_id": 1}

    def test_capture_without_textures_is_infrastructure(self):
        with self.assertRaises(G3.GateAbort) as ctx:
            G3.run("x.rdc", warmup=0, mgr=self._NoTextures(pids=[1]))
        self.assertIn("no textures", str(ctx.exception))

    def test_infrastructure_exit_code_is_distinct(self):
        self.assertEqual(G3.EXIT_CODES[G3.INFRA], 3)
        self.assertEqual(G3.EXIT_CODES[G3.UNKNOWN], 4)
        self.assertEqual(G3.EXIT_CODES[G3.REGRESSION], 2)
        self.assertEqual(G3.EXIT_CODES[G3.PASS], 0)
        self.assertEqual(len(set(G3.EXIT_CODES.values())), 4)

    def test_abort_path_yields_infrastructure_verdict(self):
        """The CLI path must map an abort to INFRASTRUCTURE_FAILURE, not UNKNOWN."""
        mgr = self._BadMgr(pids=[1])
        try:
            G3.run("x.rdc", warmup=0, mgr=mgr)
            outcome = G3.PASS
        except G3.GateAbort:
            outcome = G3.INFRA
        self.assertEqual(outcome, G3.INFRA)
        self.assertNotEqual(outcome, G3.UNKNOWN)
        self.assertNotEqual(outcome, G3.PASS)

    def test_cli_exits_with_the_infrastructure_code_on_abort(self):
        """End-to-end control for the main() path.

        The control above only exercises the mapping as written in this test
        file, so it cannot fail when main() is changed. A revert that made
        main() report an environment abort as UNKNOWN passed every other
        control; only a control that actually runs main() catches that. An
        unopenable capture aborts before any semantic work, so this needs
        neither a GPU nor a worker.
        """
        missing = os.path.join(REPO_ROOT, "tests", "workload", "corpus",
                               "no_such_capture_for_gate3.rdc")
        self.assertFalse(os.path.exists(missing))
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "cold_warm_gate.py"),
             missing],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=REPO_ROOT, timeout=600,
        )
        self.assertNotEqual(
            proc.returncode, G3.EXIT_CODES[G3.UNKNOWN],
            "an environment abort must not be reported as UNKNOWN",
        )
        self.assertNotEqual(proc.returncode, G3.EXIT_CODES[G3.PASS])
        self.assertNotEqual(proc.returncode, G3.EXIT_CODES[G3.REGRESSION])
        self.assertEqual(
            proc.returncode, G3.EXIT_CODES[G3.INFRA],
            f"an unopenable capture is an infrastructure failure, "
            f"got {proc.returncode}",
        )
        self.assertIn(G3.INFRA, proc.stdout)


class TestRealRun(unittest.TestCase):
    """Positive control on the state the project is actually in."""

    CAPTURE = os.path.join(REPO_ROOT, "tests", "workload", "corpus",
                           "w00001_frame11.rdc")

    def setUp(self):
        if not os.path.exists(self.CAPTURE):
            self.skipTest("capture not present")
        from rdebug.adapter.locator import find_module_dir

        if find_module_dir() is None:
            self.skipTest("renderdoc module not importable")

    def test_real_capture_passes_and_proves_the_boundary(self):
        verdict = G3.run(self.CAPTURE, warmup=2)
        self.assertEqual(verdict["outcome"], G3.PASS,
                         "differences: {}".format(json.dumps(verdict["cases"], default=str)[:600]))
        ev = verdict["evidence"]
        self.assertTrue(ev["same_worker_within_A"])
        self.assertTrue(ev["recycle_produced_new_worker"])
        self.assertNotEqual(ev["workers"]["A_cold"], ev["workers"]["B_cold"])

    def test_high_risk_shader_values_case_really_ran(self):
        verdict = G3.run(self.CAPTURE, warmup=1)
        case = verdict["cases"]["diff_pixel_shader_values"]
        self.assertIn(case["verdict"], (G3.PASS, G3.UNKNOWN, G3.REGRESSION))
        self.assertEqual(
            case["attempted"], 4,
            "the shader-values case must be attempted at all four collection "
            "points, not dropped",
        )
        self.assertGreater(
            case["available_at"], 0,
            "the shader-values case must have produced a payload somewhere; an "
            "unavailable-everywhere case is a different finding",
        )

    def test_every_case_reports_its_execution_accounting(self):
        """The report must be able to say what ran, not only that all passed."""
        verdict = G3.run(self.CAPTURE, warmup=1)
        for cid, case in verdict["cases"].items():
            self.assertIn("attempted", case, cid)
            self.assertIn("available_at", case, cid)
            self.assertEqual(case["attempted"], 4, cid)
            self.assertLessEqual(case["available_at"], case["attempted"], cid)


if __name__ == "__main__":
    unittest.main()
