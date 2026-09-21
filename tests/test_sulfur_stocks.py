"""Missing observations must never become zero, estimates, or partial aggregates."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from export_sulfur_stocks import METRICS, chart_rows, classify, number


class SulfurStocksTests(unittest.TestCase):
    def test_exact_stock_categories(self):
        for label, metric in zip(('0 to 15', 'Greater than 15 to 500', 'Greater Than 500'), METRICS):
            self.assertEqual(classify(f'Weekly New England (PADD 1A ) Ending Stocks of Distillate Fuel Oil, {label} ppm Sulfur (Thousand Barrels)'), ('padd1a', metric))
        self.assertIsNone(classify('U.S. Production of Distillate Fuel Oil, 0 to 15 ppm Sulfur'))

    def test_sum_and_missing_components(self):
        values = {(region, metric): amount for region, amount in [('padd1a', 0), ('padd1b', 5), ('padd1', 12), ('padd2', 20), ('padd3', 30)] for metric in METRICS}
        rows = {r['regionKey']: r for r in chart_rows({'2026-01': values})}
        self.assertEqual(rows['padd1ab'][METRICS[0]], 5)
        self.assertEqual(rows['padd1ab']['sulfurOver15StocksKb'], 10)
        self.assertEqual(rows['p123'][METRICS[0]], 62)
        self.assertEqual(rows['p13'][METRICS[0]], 42)
        del values[('padd1a', METRICS[2])]
        ab = next(r for r in chart_rows({'2026-01': values}) if r['regionKey'] == 'padd1ab')
        self.assertIsNone(ab[METRICS[2]])
        self.assertIsNone(ab['sulfurOver15StocksKb'])
        self.assertEqual(ab['status'], 'actual')

    def test_suppressed_is_not_zero(self):
        for value in [None, '', '--', 'NA', 'W', float('nan')]:
            self.assertIsNone(number(value))
        self.assertEqual(number(0), 0)


if __name__ == '__main__':
    unittest.main()
