#!/usr/bin/env python3
"""Manual, local SemiAnalysis GPU archive. Python 3.9+; no dependencies."""
import argparse
import csv
import datetime as dt
import io
import json
import math
from pathlib import Path
import sys
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

URL = 'https://gpu-index.semianalysis.com/api/public-data'
USER_AGENT = 'PersonalGPUArchive/1.0 (manual local archival script; Python urllib)'
INDEX_FIELDS = ['date', 'a100_usd_per_gpu_hour', 'h100_usd_per_gpu_hour',
                'b200_usd_per_gpu_hour']
CONTRACT_FIELDS = ['date', 'period', 'h100_1y_p25_usd_per_gpu_hour',
                   'h100_1y_p75_usd_per_gpu_hour',
                   'h100_onDemand_p25_usd_per_gpu_hour',
                   'h100_onDemand_p75_usd_per_gpu_hour',
                   'h100_1y_sold_out', 'h100_onDemand_sold_out']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # A redirect must not cause a second GET.


def date_key(value):
    if not isinstance(value, str):
        raise ValueError('Missing or invalid source date')
    try:
        result = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    # Keep the source calendar day, not the machine's local timezone day.
    return result.date().isoformat()


def number(value):
    if value is None:
        return ''
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Expected a number or null, got ' + repr(value))
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid price: ' + repr(value))
    return str(value)


def bounds(value):
    if value is None:
        return ['', '']
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('Expected a two-number contract range')
    low, high = [number(v) for v in value]
    if not low or not high or float(low) > float(high):
        raise ValueError('Invalid contract range: ' + repr(value))
    return [low, high]


def unique_rows(rows):
    result = {}
    for row in rows:
        if row[0] in result and result[row[0]] != row:
            raise ValueError('Conflicting source rows for ' + row[0])
        result[row[0]] = row
    return [result[key] for key in sorted(result)]


def parse(payload):
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        raise ValueError('Source did not return status=ok')
    if not isinstance(payload.get('index'), list) or not payload['index']:
        raise ValueError('Missing or empty index')
    daily = []
    for point in payload['index']:
        if not isinstance(point, dict) or not {'date', 'a100', 'h100', 'b200'} <= point.keys():
            raise ValueError('Index schema changed; raw response retained')
        daily.append([date_key(point['date'])] +
                     [number(point[key]) for key in ['a100', 'h100', 'b200']])
    contracts = payload.get('contract')
    if not isinstance(contracts, list):
        raise ValueError('Missing contract list')
    selected = [block for block in contracts if block.get('sku') == 'H100']
    if len(selected) != 1:
        raise ValueError('Expected exactly one H100 contract block')
    block = selected[0]
    if not isinstance(block.get('data'), list) or not block['data']:
        raise ValueError('Missing or empty H100 contract data')
    sold = block.get('soldOutPeriods', {})
    if not isinstance(sold, dict):
        raise ValueError('Invalid soldOutPeriods')
    if set(sold) - {'1y', 'onDemand'}:
        raise ValueError('New contract term in soldOutPeriods; update parser')
    for periods in sold.values():
        if not isinstance(periods, list) or any(not isinstance(p, str) for p in periods):
            raise ValueError('Invalid sold-out period list')
    contract_rows = []
    for point in block['data']:
        if set(point) - {'period_start', 'period', '1y', 'onDemand'}:
            raise ValueError('New contract field or term; raw retained; update parser')
        period = point['period']
        if not isinstance(period, str) or not period or '\n' in period or '\r' in period:
            raise ValueError('Invalid contract period')
        contract_rows.append([date_key(point['period_start']), period] +
                             bounds(point.get('1y')) + bounds(point.get('onDemand')) +
                             ['true' if period in sold.get(term, []) else 'false'
                              for term in ['1y', 'onDemand']])
    return unique_rows(daily), unique_rows(contract_rows)


def pending(path, fields, rows):
    existing = {}
    if path.exists():
        text = path.read_text(encoding='utf-8')
        if not text.endswith('\n'):
            raise ValueError(str(path) + ': missing final newline; check file manually')
        reader = csv.reader(io.StringIO(text, newline=''))
        if next(reader, None) != fields:
            raise ValueError(str(path) + ': CSV header does not match')
        for row in reader:
            if len(row) != len(fields) or row[0] in existing:
                raise ValueError(str(path) + ': malformed or duplicate dated rows')
            if dt.date.fromisoformat(row[0]).isoformat() != row[0]:
                raise ValueError(str(path) + ': invalid date')
            existing[row[0]] = row
    revised = sum(row[0] in existing and existing[row[0]] != row for row in rows)
    if revised:
        print('Warning: {} source dates differ from {}. Existing rows are unchanged; '
              'see the raw snapshot for revisions.'.format(revised, path.name), file=sys.stderr)
    return [row for row in rows if row[0] not in existing]


def append(path, fields, rows):
    if not rows:
        return
    new_file = not path.exists()
    with path.open('a', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(fields)
        writer.writerows(rows)


def run(args):
    folder = args.output_dir.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / '.archive.lock'
    try:
        lock_fd = lock.open('x')
    except FileExistsError:
        raise ValueError('Another run may be active. If a prior run crashed, remove '
                         + str(lock) + ' only after checking no run is active.')
    try:
        if args.from_snapshot:
            body = args.from_snapshot.read_bytes()
            print('Offline replay: no network request')
        else:
            request = urllib.request.Request(URL, headers={
                'User-Agent': USER_AGENT, 'Accept': 'application/json'})
            # Exactly one GET, no authentication, redirects, retries, or scheduling.
            opener = urllib.request.build_opener(NoRedirect)
            try:
                with opener.open(request, timeout=30) as response:
                    body = response.read()
            except urllib.error.HTTPError as exc:
                raise ValueError('HTTP {}: stopped without retry. Respect any '
                                 'Retry-After header and site limits.'.format(exc.code)) from exc
        raw_folder = folder / 'raw'
        raw_folder.mkdir(exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        raw_path = raw_folder / (stamp + ('-offline' if args.from_snapshot else '') + '.json')
        with raw_path.open('xb') as handle:
            handle.write(body)
        print('Raw snapshot:', raw_path)
        daily, contracts = parse(json.loads(body))
        daily_path, contract_path = folder / 'gpu_index.csv', folder / 'h100_contracts.csv'
        # Validate both CSVs before changing either. Interrupted appends fail visibly.
        new_daily = pending(daily_path, INDEX_FIELDS, daily)
        new_contracts = pending(contract_path, CONTRACT_FIELDS, contracts)
        append(daily_path, INDEX_FIELDS, new_daily)
        append(contract_path, CONTRACT_FIELDS, new_contracts)
        print('Appended {} daily dates and {} H100 contract period dates.'.format(
            len(new_daily), len(new_contracts)))
        print('Latest index source date:', daily[-1][0])
        print('Latest H100 contract period:', contracts[-1][1])
    finally:
        lock_fd.close()
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'gpu_archive',
                        help='Local data directory (default: gpu_archive next to script)')
    parser.add_argument('--from-snapshot', type=Path,
                        help='Offline replay of a saved JSON response; makes no request')
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Stopped: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
