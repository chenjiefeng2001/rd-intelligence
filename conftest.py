"""Make the two test trees collectable in one pytest process.

`tests_transport` is imported two different ways on purpose. The release gate runs
`python -m unittest discover -s tests_transport`, which puts that directory on
`sys.path` and imports the modules as top level -- so their bare
`from test_transport import FakeSession` resolves. pytest does not do that, and
`pyproject.toml` lists both trees in `testpaths`, so a bare `pytest` failed
collection on every module in `tests_transport` while still collecting the other
913 tests.

Adding the directory here satisfies both: the gate never loads this file, and
pytest gets the same `sys.path` the gate already provides. Rewriting the imports
as relative would have fixed pytest and broken the gate, which is the wrong trade
for a frozen transport surface.
"""
import os
import sys

_TRANSPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "tests_transport")

if _TRANSPORT not in sys.path:
    sys.path.insert(0, _TRANSPORT)
