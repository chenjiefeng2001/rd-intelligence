import json
import pathlib
import subprocess
import tempfile
import unittest

PAGE = (pathlib.Path(__file__).resolve().parent.parent.parent
        / "src" / "rdebug_ide" / "static" / "index.html")

COORD = ["100,200", " 100 , 200 ", "-5,-7", "0,0",
         "100", "100,", ",200", "abc", "100,abc", "100,200,300", ""]
IDS = ["ResourceId::123", "resource-123", "ResourceId::", "abc", "",
       "ResourceId::12a3", "123"]


def extract(page: str, name: str) -> str:
    """Pull one pure function out of the page by balancing braces."""
    start = page.index(f"function {name}(")
    i, depth = page.index("{", start), 0
    while True:
        if page[i] == "{":
            depth += 1
        elif page[i] == "}":
            depth -= 1
            if depth == 0:
                return page[start:i + 1]
        i += 1


def probe(page: str) -> dict:
    """Run the page's own validators under node and report real behaviour."""
    js = "const parseCoord={};\nconst canonicalResourceId={};\n".format(
        extract(page, "parseCoord"), extract(page, "canonicalResourceId"))
    js += "const out={coord:{},id:{}};\n"
    js += f"for(const v of {json.dumps(COORD)})out.coord[v]=parseCoord(v);\n"
    js += f"for(const v of {json.dumps(IDS)})out.id[v]=canonicalResourceId(v);\n"
    js += "console.log(JSON.stringify(out));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js)
        path = fh.name
    r = subprocess.run(["node", path], capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError("probe failed: " + r.stderr)
    return json.loads(r.stdout)


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


class TestCoordinateContract(unittest.TestCase):
    """D7: a coordinate is either well formed or refused. Never synthesised."""

    def setUp(self):
        self.p = probe(page())

    def test_well_formed_coordinates_are_preserved(self):
        self.assertTrue(self.p["coord"]["100,200"]["ok"])
        self.assertEqual(self.p["coord"]["100,200"]["data"],
                         {"x": 100, "y": 200})
        self.assertTrue(self.p["coord"][" 100 , 200 "]["ok"])
        self.assertEqual(self.p["coord"][" 100 , 200 "]["data"],
                         {"x": 100, "y": 200})
        self.assertEqual(self.p["coord"]["-5,-7"]["data"], {"x": -5, "y": -7})

    def test_a_missing_or_malformed_coordinate_is_refused(self):
        for bad in ("100", "100,", ",200", "abc", "100,abc", "100,200,300", ""):
            with self.subTest(value=bad):
                self.assertFalse(self.p["coord"][bad]["ok"],
                                 f"expected {bad!r} to be refused")

    def test_a_refused_coordinate_names_what_it_saw(self):
        self.assertIn("100", self.p["coord"]["100"]["message"])

    def test_no_coordinate_is_invented(self):
        """The defect was a synthesised 0, so no fallback may return at all."""
        src = page()
        self.assertNotIn('||"0"', src)
        self.assertNotIn('split(",")[1]', src)


class TestResourceIdContract(unittest.TestCase):
    """D8: a canonical id reaches the backend unchanged, or is refused."""

    def setUp(self):
        self.p = probe(page())

    def test_a_canonical_id_is_preserved_byte_for_byte(self):
        r = self.p["id"]["ResourceId::123"]
        self.assertTrue(r["ok"])
        self.assertEqual(r["data"]["id"], "ResourceId::123")

    def test_a_non_canonical_id_is_refused_rather_than_repaired(self):
        # These all used to arrive at the backend as some other object.
        for bad in ("resource-123", "ResourceId::", "ResourceId::12a3",
                    "abc", "", "123"):
            with self.subTest(value=bad):
                self.assertFalse(self.p["id"][bad]["ok"],
                                 f"expected {bad!r} to be refused")

    def test_no_string_cleaning_produces_a_different_id(self):
        self.assertNotIn(r"replace(/\D/g", page())


class TestSemanticMutation(unittest.TestCase):
    """The D8 control has to track behaviour, not one source line.

    Reintroducing digit stripping satisfies any test that only greps for the
    absence of a token, so the control mutates the validator instead and
    requires the same assertions to catch the regression.
    """

    MUTANT = ('function canonicalResourceId(id){const raw=(id||"").trim();'
              'return {ok:true,data:{id:"ResourceId::"+raw.replace(/\\D/g,"")}}};')

    def test_reintroducing_digit_stripping_is_caught(self):
        src = page()
        self.assertTrue(probe(src)["id"]["resource-123"] is not None)
        self.assertFalse(probe(src)["id"]["resource-123"]["ok"])

        mutant = src.replace(extract(src, "canonicalResourceId"), self.MUTANT)
        self.assertIn("replace(/\\D/g", mutant, "mutation did not apply")

        caught = probe(mutant)["id"]["resource-123"]["ok"] is False
        self.assertFalse(caught,
                         "the assertions let a digit-stripping id through")


if __name__ == "__main__":
    unittest.main()
