import unittest
from types import SimpleNamespace

from caos.company.chat import CompanyChatService


class EchoLLM:
    def __init__(self):
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        return "A Company está parada e sem exposição."


class FakeCompany:
    def status(self):
        return {
            "operational_state": "stopped",
            "policy": {
                "trader_initial_bucket": 10,
                "trader_stop_floor": 3,
                "default_trader_max_exposure_pct": 20,
                "company_max_drawdown_pct": 30,
                "operational_trader_cap": 6,
            },
            "marked_company_equity": 10.0,
            "treasury": {"reserve": 0.0},
            "exposure": {"gross_notional": 0.0},
            "risk": {
                "drawdown_pct": 0.0,
                "kill_switch": False,
            },
            "traders": {
                "traders": {
                    "A": {
                        "status": "waiting_assignment",
                        "market": None,
                        "direction": None,
                        "strategy_id": None,
                        "mode": "production",
                        "max_trade_exposure_pct": 20,
                        "trade_exposure_pct": None,
                    }
                }
            },
            "assignments": {},
            "audit": {"status": "healthy", "alerts": []},
            "news_intelligence": {"contexts": {}},
        }


class CompanyChatTests(unittest.TestCase):
    def test_chat_is_read_only_and_keeps_short_history(self):
        llm = EchoLLM()
        service = CompanyChatService(
            SimpleNamespace(llm=llm),
            FakeCompany(),
            execution_service=SimpleNamespace(
                status=lambda: {"mode": "paper"}
            ),
        )
        result = service.ask("O que os agentes estão fazendo?")
        self.assertTrue(result["read_only"])
        self.assertEqual(len(result["history"]), 2)
        self.assertIn("cannot execute trades", llm.calls[0][0])
        self.assertIn("stopped", llm.calls[0][1])

        cleared = service.clear()
        self.assertTrue(cleared["cleared"])
        self.assertEqual(service.messages(), [])


if __name__ == "__main__":
    unittest.main()
