"""Chart-only sulfur inventories and flows. No forecasts or balance inputs."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from zipfile import ZipFile

OUTPUT = Path('eia_monthly/distillate_sulfur_stocks.json')
CATEGORIES = ('0To15', '15To500', 'Over500')
MEASURES = ('StocksKb', 'ProductionKbd', 'ImportsKbd', 'ExportsKbd')
METRICS = tuple('sulfur' + category + 'StocksKb' for category in CATEGORIES)
BASE_METRICS = tuple('sulfur' + category + measure for measure in MEASURES for category in CATEGORIES)
SERIES_PATTERN = re.compile(
    r'^(?:Weekly )?(.+?) (Ending Stocks of|Refinery and Blender Net Production of|'
    r'Refiner and Blender Net Production of|Production of|Imports of|Exports of) '
    r'Distillate Fuel Oil,? (0 to 15|Greater than 15 to 500|Greater than 500|'
    r'Greater than 500 to 2000|Greater than 2000) ppm Sulfur'
    r'(?:, (?:Monthly|Weekly))?(?: \(Thousand Barrels(?: per Day)?\))?$', re.I)

REGIONS = {
    'padd1': ('padd1',),
    'padd1ab': ('padd1a', 'padd1b'), 'padd1c': ('padd1c',),
    'padd2': ('padd2',), 'padd3': ('padd3',), 'padd4': ('padd4',),
    'padd5': ('padd5',), 'us': ('us',),
    'p123': ('padd1', 'padd2', 'padd3'), 'p13': ('padd1', 'padd3'),
}


def classify(name):
    # Exact total-flow names exclude bilateral trade, bonded subsets, refinery-only
    # production, rolling averages, and overlapping sulfur buckets.
    name = ' '.join(name.replace(')Refiner', ') Refiner').split())
    match = SERIES_PATTERN.fullmatch(name)
    if not match:
        return None
    area, operation, sulfur = match.groups()
    region_match = re.search(r'\(PADD ([1-5])\s*([ABC])?\s*\)$', area)
    region = 'padd' + region_match[1] + (region_match[2] or '').lower() if region_match else 'us' if area == 'U.S.' else None
    if not region:
        return None
    category = {'0 to 15': '0To15', 'greater than 15 to 500': '15To500',
                'greater than 500': 'Over500', 'greater than 500 to 2000': '500To2000',
                'greater than 2000': 'Over2000'}[sulfur.lower()]
    operation = operation.lower()
    measure = 'StocksKb' if operation == 'ending stocks of' else 'ImportsKbd' if operation == 'imports of' else 'ExportsKbd' if operation == 'exports of' else 'ProductionKbd'
    if category in ('500To2000', 'Over2000') and measure != 'ImportsKbd':
        return None
    return region, 'sulfur' + category + measure


def expected_units(metric):
    return 'Thousand Barrels' if metric.endswith('StocksKb') else 'Thousand Barrels per Day'


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
        # EIA weekly >500 ppm imports are published as >500–2000 plus >2000.
        # Neither missing component is treated as zero.
        period_values = dict(values[period])
        for source_region in {key[0] for key in period_values}:
            key = (source_region, 'sulfurOver500ImportsKbd')
            if period_values.get(key) is None:
                parts = [period_values.get((source_region, 'sulfur' + category + 'ImportsKbd'))
                         for category in ('500To2000', 'Over2000')]
                if all(value is not None for value in parts):
                    period_values[key] = sum(parts)
        for region, members in REGIONS.items():
            row = dict(period=period, regionKey=region, status='actual')
            for metric in BASE_METRICS:
                parts = [period_values.get((member, metric)) for member in members]
                row[metric] = sum(parts) if all(value is not None for value in parts) else None
                if region == 'padd1ab' and row[metric] is None:
                    total = period_values.get(('padd1', metric))
                    lower_atlantic = period_values.get(('padd1c', metric))
                    if total is not None and lower_atlantic is not None:
                        row[metric] = total - lower_atlantic
            for measure in MEASURES:
                low, high = (row['sulfur' + category + measure] for category in ('15To500', 'Over500'))
                row['sulfurOver15' + measure] = low + high if low is not None and high is not None else None
            if any(row[metric] is not None for metric in BASE_METRICS):
                rows.append(row)
    return rows


def export_sulfur_stocks(mode='all', bulk_path=None):
    result = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {'monthly': [], 'weekly': [], 'sources': {}}
    result['note'] = 'Actual EIA sulfur inventories (thousand barrels) and production/import/export flows (thousand barrels per day). PADD 1A+B sums reported A and B, falling back to reported PADD 1 minus PADD 1C when a component is missing; unavailable residual inputs remain gaps. Combined >15 ppm sums >15–500 and >500 ppm. No forecasts.'
    if mode in ('monthly', 'all') and bulk_path and Path(bulk_path).exists():
        values, sources = {}, {}
        with ZipFile(bulk_path) as archive:
            with archive.open(archive.namelist()[0]) as stream:
                for line in stream:
                    item = json.loads(line)
                    key = classify(item.get('name', ''))
                    if item.get('f') != 'M' or not key or item.get('units') != expected_units(key[1]):
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
                        columns = {i: key for i, key in columns.items() if key and '(' + expected_units(key[1]) + ')' in str(sheet.cell_value(2, i))}
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
    print(f"Distillate split actuals: {len(data['monthly'])} monthly, {len(data['weekly'])} weekly rows")
