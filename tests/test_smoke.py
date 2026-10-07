import unittest

from caos.cli import synthetic_bars
from caos.domain import Mandate
from caos.llm import StaticLLM
from caos.orchestrator import CAOS


class SmokeTests(unittest.TestCase):
    def test_end_to_end_paper_flow(self):
        c = CAOS(
            StaticLLM(
                '{"tool":"status","args":{}}'
            )
        )
        c.set_mandate(
            Mandate(
                1000,
                25,
                max_position_pct=20,
            )
        )
        c.load_bars(
            "DEMOUSDT",
            synthetic_bars(500),
        )
        mined = c.tool_mine(
            "DEMOUSDT"
        )
        self.assertIn(
            "approved",
            mined,
        )
        status = c.status()
        self.assertEqual(
            status["orchestrator"],
            "local_llm",
        )
        fill = c.tool_paper_order(
            "DEMOUSDT",
            "buy",
            100,
            100,
            "smoke",
        )
        self.assertEqual(
            fill["side"],
            "buy",
        )
        c.tool_kill()
        self.assertTrue(
            c.status()["kill_switch"]
        )


if __name__ == "__main__":
    unittest.main()
