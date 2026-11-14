import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"

def rows(name):
    with (OUT / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

class ECE004IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bills = {r["subscriber_id"]: r for r in rows("bills.csv")}
        cls.status = rows("daily_status.csv")
        cls.errors = rows("errors.csv")

    def test_exact_cap_and_next_day_throttle(self):
        a = next(r for r in self.status if r["subscriber_id"] == "SUB-003" and r["date"] == "2026-10-21")
        b = next(r for r in self.status if r["subscriber_id"] == "SUB-003" and r["date"] == "2026-10-22")
        self.assertEqual(a["state"], "FULL_SPEED")
        self.assertEqual(a["speed_mbps"], "50")
        self.assertEqual(a["cumulative_weighted_gb"], "204.13")
        self.assertEqual(b["state"], "THROTTLED")
        self.assertEqual(b["speed_mbps"], "2")

    def test_upgrade_proration_boundaries(self):
        self.assertEqual(self.bills["SUB-007"]["upgrade_prorata_rs"], "600.00")
        self.assertEqual(self.bills["SUB-008"]["upgrade_prorata_rs"], "10.00")
        self.assertEqual(self.bills["SUB-009"]["upgrade_prorata_rs"], "350.00")

    def test_topups(self):
        self.assertEqual(self.bills["SUB-005"]["topup_count"], "1")
        self.assertEqual(self.bills["SUB-010"]["topup_count"], "2")
        self.assertEqual(self.bills["SUB-010"]["topup_charge_rs"], "298.00")

    def test_payment_suspension_and_resume(self):
        self.assertEqual(self.bills["SUB-012"]["suspended_days"], "5")
        self.assertEqual(self.bills["SUB-012"]["total_weighted_gb"], "196.50")

    def test_late_fee_boundary(self):
        self.assertEqual(self.bills["SUB-013"]["late_fee_rs"], "100.00")
        self.assertEqual(self.bills["SUB-016"]["late_fee_rs"], "0.00")

    def test_downgrades_deferred(self):
        self.assertEqual(self.bills["SUB-014"]["plan_id"], "PLN-03")
        self.assertEqual(self.bills["SUB-014"]["next_cycle_plan_id"], "PLN-01")
        self.assertEqual(self.bills["SUB-015"]["plan_id"], "PLN-04")
        self.assertEqual(self.bills["SUB-015"]["next_cycle_plan_id"], "PLN-02")

    def test_validation_errors(self):
        pairs = {(r["source"], r["line_no"]) for r in self.errors}
        self.assertTrue({("usage.csv", "902"), ("usage.csv", "903"),
                         ("commands.txt", "17")}.issubset(pairs))
        suspended = [r for r in self.errors if r["source"] == "usage.csv"
                     and r["line_no"] in {"341", "342", "343", "344", "345"}]
        self.assertEqual(len(suspended), 5)

    def test_output_cardinality(self):
        self.assertEqual(len(self.bills), 30)
        self.assertEqual(len(self.status), 4)

if __name__ == "__main__":
    unittest.main(verbosity=2)
