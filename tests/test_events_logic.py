import unittest

from rdebug.query.events import build_action_index, filter_rows, flatten_actions


class FakeAction:
    _next_id = [1]

    def __init__(self, event_id=None, name="", flags=0, children=None):
        self.eventId = event_id if event_id is not None else FakeAction._next_id[0]
        FakeAction._next_id[0] += 1
        self.actionId = self.eventId
        self.customName = name
        self.flags = flags
        self.numIndices = 3
        self.numInstances = 1
        self.children = children or []


DRAW = 1 << 10
MARKER = 1 << 12


def sample_tree():
    return [
        FakeAction(1, "FrameStart", MARKER),
        FakeAction(
            5,
            "",
            DRAW,
            children=[
                FakeAction(6, "Pass", 0, children=[FakeAction(7, "Triangle", DRAW)]),
            ],
        ),
        FakeAction(20, "Clear", DRAW),
    ]


class TestFlattenActions(unittest.TestCase):
    def test_flatten_order_and_depth(self):
        rows = flatten_actions(sample_tree(), draw_flag=DRAW)
        eids = [r["eventId"] for r in rows]
        self.assertEqual(eids, [1, 5, 6, 7, 20])
        by_eid = {r["eventId"]: r for r in rows}
        self.assertEqual(by_eid[1]["depth"], 0)
        self.assertEqual(by_eid[6]["depth"], 1)
        self.assertEqual(by_eid[7]["depth"], 2)
        self.assertEqual(by_eid[6]["parentEventId"], 5)
        self.assertTrue(by_eid[5]["isDraw"])
        self.assertFalse(by_eid[1]["isDraw"])
        self.assertEqual(by_eid[7]["name"], "Triangle")

    def test_filter_range_name_draws_limit(self):
        rows = flatten_actions(sample_tree(), draw_flag=DRAW)
        draws_only = filter_rows(rows, only_draws=True)
        self.assertEqual([r["eventId"] for r in draws_only], [5, 7, 20])
        ranged = filter_rows(rows, min_eid=6, max_eid=19)
        self.assertEqual([r["eventId"] for r in ranged], [6, 7])
        named = filter_rows(rows, name="tri")
        self.assertEqual([r["eventId"] for r in named], [7])
        limited = filter_rows(rows, limit=2)
        self.assertEqual(len(limited), 2)

    def test_action_index(self):
        index = build_action_index(flatten_actions(sample_tree()))
        self.assertEqual(index[7]["name"], "Triangle")


if __name__ == "__main__":
    unittest.main()
