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
        self.assertEqual(classify('U.S. Production of Distillate Fuel Oil, 0 to 15 ppm Sulfur'), ('us', 'sulfur0To15ProductionKbd'))

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

    def test_northeast_actual_residual_fallback(self):
        values = {(region, metric): amount for region, amount in
                  [('padd1a', 2), ('padd1b', 5), ('padd1', 12), ('padd1c', 3)]
                  for metric in METRICS}
        del values[('padd1a', METRICS[2])]
        ab = next(r for r in chart_rows({'2026-05': values}) if r['regionKey'] == 'padd1ab')
        self.assertEqual(ab[METRICS[0]], 7)  # Direct A+B remains authoritative.
        self.assertEqual(ab[METRICS[2]], 9)  # Missing A: total PADD 1 minus C.
        self.assertEqual(ab['sulfurOver15StocksKb'], 16)
        self.assertEqual(ab['status'], 'actual')
        del values[('padd1', METRICS[2])]
        ab = next(r for r in chart_rows({'2026-05': values}) if r['regionKey'] == 'padd1ab')
        self.assertIsNone(ab[METRICS[2]])

    def test_flow_series_exclude_overlapping_subsets(self):
        self.assertEqual(classify('Weekly Midwest (PADD 2)Refiner and Blender Net Production of Distillate Fuel Oil, Greater than 15 to 500 ppm Sulfur (Thousand Barrels per Day)'), ('padd2', 'sulfur15To500ProductionKbd'))
        self.assertEqual(classify('U.S. Exports of Distillate Fuel Oil, 0 to 15 ppm Sulfur, Monthly'), ('us', 'sulfur0To15ExportsKbd'))
        for name in [
            'U.S. Imports of Distillate Fuel Oil, 0 to 15 ppm Sulfur, Not Bonded, Monthly',
            'U.S. Imports of Distillate Fuel Oil, 0 to 15 ppm Sulfur from Canada, Monthly',
            'U.S. Refinery Net Production of Distillate Fuel Oil, 0 to 15 ppm Sulfur, Monthly',
            '4-Week Avg U.S. Refiner and Blender Net Production of Distillate Fuel Oil, 0 to 15 ppm Sulfur',
            'U.S. Exports of Distillate Fuel Oil, Greater than 500 to 2000 ppm Sulfur, Monthly',
        ]:
            self.assertIsNone(classify(name), name)

    def test_weekly_import_buckets_and_negative_net_production(self):
        values = {('us', 'sulfur500To2000ImportsKbd'): 3,
                  ('us', 'sulfurOver2000ImportsKbd'): 4,
                  ('us', 'sulfur15To500ImportsKbd'): 2,
                  ('us', 'sulfur15To500ProductionKbd'): -1,
                  ('us', 'sulfurOver500ProductionKbd'): 4}
        row = next(r for r in chart_rows({'2026-09-11': values}) if r['regionKey'] == 'us')
        self.assertEqual(row['sulfurOver500ImportsKbd'], 7)
        self.assertEqual(row['sulfurOver15ImportsKbd'], 9)
        self.assertEqual(row['sulfurOver15ProductionKbd'], 3)
        self.assertIsNone(row['sulfur0To15ExportsKbd'])
        del values[('us', 'sulfurOver2000ImportsKbd')]
        row = next(r for r in chart_rows({'2026-09-11': values}) if r['regionKey'] == 'us')
        self.assertIsNone(row['sulfurOver500ImportsKbd'])
        self.assertIsNone(row['sulfurOver15ImportsKbd'])

    def test_suppressed_is_not_zero(self):
        for value in [None, '', '--', 'NA', 'W', float('nan')]:
            self.assertIsNone(number(value))
        self.assertEqual(number(0), 0)


if __name__ == '__main__':
    unittest.main()
