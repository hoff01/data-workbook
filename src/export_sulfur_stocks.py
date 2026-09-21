"""Chart-only distillate stocks. No estimates, interpolation, or balance inputs."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from zipfile import ZipFile

OUTPUT = Path('eia_monthly/distillate_sulfur_stocks.json')
METRICS = ('sulfur0To15StocksKb', 'sulfur15To500StocksKb', 'sulfurOver500StocksKb')
REGIONS = {
    'padd1ab': ('padd1a', 'padd1b'), 'padd1c': ('padd1c',),
    'padd2': ('padd2',), 'padd3': ('padd3',), 'padd4': ('padd4',),
    'padd5': ('padd5',), 'us': ('us',),
    'p123': ('padd1', 'padd2', 'padd3'), 'p13': ('padd1', 'padd3'),
}


def classify(name):
    if 'Ending Stocks of Distillate Fuel Oil' not in name or 'ppm Sulfur' not in name:
        return None
    metric = next((METRICS[i] for i, phrase in enumerate(('0 to 15 ppm', '15 to 500 ppm', '500 ppm')) if phrase in name), None)
    match = re.search(r'PADD ([1-5])\s*([ABC])?', name)
    region = 'padd' + match[1] + (match[2] or '').lower() if match else 'us' if 'U.S.' in name else None
    return (region, metric) if region and metric else None


def number(value):
    if isinstance(value, bool) or value is None or value == '':
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def chart_rows(values):
    rows = []
    for period in sorted(values):
        for region, members in REGIONS.items():
            row = dict(period=period, regionKey=region, status='actual')
            for metric in METRICS:
                parts = [values[period].get((member, metric)) for member in members]
                row[metric] = sum(parts) if all(value is not None for value in parts) else None
            low, high = row[METRICS[1]], row[METRICS[2]]
            row['sulfurOver15StocksKb'] = low + high if low is not None and high is not None else None
            if any(row[metric] is not None for metric in METRICS):
                rows.append(row)
    return rows


def export_sulfur_stocks(mode='all', bulk_path=None):
    result = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {'monthly': [], 'weekly': [], 'sources': {}}
    result['note'] = 'Actual EIA ending stocks only, thousand barrels. PADD 1A+B sums reported A and B; missing components remain gaps. Combined >15 ppm sums >15–500 and >500 ppm. No forecasts.'
    if mode in ('monthly', 'all') and bulk_path and Path(bulk_path).exists():
        values, sources = {}, {}
        with ZipFile(bulk_path) as archive:
            with archive.open(archive.namelist()[0]) as stream:
                for line in stream:
                    item = json.loads(line)
                    key = classify(item.get('name', ''))
                    if item.get('f') != 'M' or item.get('units') != 'Thousand Barrels' or not key:
                        continue
                    sources['|'.join(key)] = item['series_id']
                    for raw_period, value in item.get('data', []):
                        period = raw_period[:4] + '-' + raw_period[4:6]
                        if period >= '2017-01':
                            values.setdefault(period, {})[key] = number(value)
        result['monthly'], result['sources']['monthly'] = chart_rows(values), sources
    if mode in ('weekly', 'all'):
        import xlrd
        paths = sorted(Path('eia_weekly/cache/eia_history_workbooks').glob('*.xls'))
        # WPSR wins over cached history for overlapping observations.
        paths += sorted(Path('eia_weekly/cache/wpsr_tables').glob('*.xls'))
        if paths:
            values, sources = {}, {}
            for path in paths:
                book = xlrd.open_workbook(str(path), on_demand=True)
                try:
                    for sheet in book.sheets():
                        if not sheet.name.startswith('Data') or sheet.nrows < 4:
                            continue
                        columns = {i: classify(str(name)) for i, name in enumerate(sheet.row_values(2))}
                        columns = {i: key for i, key in columns.items() if key and 'Thousand Barrels)' in str(sheet.cell_value(2, i))}
                        if not columns:
                            continue
                        for i, key in columns.items():
                            sources['|'.join(key)] = str(sheet.cell_value(1, i))
                        for r in range(3, sheet.nrows):
                            date = sheet.cell_value(r, 0)
                            if not isinstance(date, (int, float)):
                                continue
                            period = xlrd.xldate_as_datetime(date, book.datemode).date().isoformat()
                            if period < '2017-01-01':
                                continue
                            for i, key in columns.items():
                                values.setdefault(period, {})[key] = number(sheet.cell_value(r, i))
                finally:
                    book.release_resources()
            result['weekly'], result['sources']['weekly'] = chart_rows(values), sources
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False) + '\n')
    return result


if __name__ == '__main__':
    from export_raw_headers import MONTHLY_BULK_SOURCE
    data = export_sulfur_stocks(bulk_path=MONTHLY_BULK_SOURCE)
    print(f"Sulfur stock actuals: {len(data['monthly'])} monthly, {len(data['weekly'])} weekly rows")
