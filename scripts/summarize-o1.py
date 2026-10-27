#!/usr/bin/env python3
"""从 O1 两轮原始数据生成汇总 CSV；不把 GC 累计值当作本轮开销。"""
import csv
from pathlib import Path
import sys


def metrics(path):
    return {line.split()[0]: float(line.split()[1])
            for line in path.read_text().splitlines()
            if line and not line.startswith('#') and len(line.split()) == 2}


def summarize(name):
    root = Path('runs') / name
    start, end = (metrics(root / f'metrics-{part}.txt') for part in ('start', 'end'))
    step = next(csv.DictReader((root / 'steps.csv').open()))
    gc = next(csv.DictReader((root / 'gc.csv').open()))
    cycles = end['go_gc_cycles_total'] - start['go_gc_cycles_total']
    cpu = end['go_gc_cpu_seconds_total'] - start['go_gc_cpu_seconds_total']
    return dict(run=name, target_rps=step['target_rps'], ok_rps=step['ok_rps'],
                error_rate=step['error_rate'], gc_cycles_delta=f'{cycles:.0f}',
                gc_cpu_seconds_delta=f'{cpu:.6f}', rss_avg_mb=gc['rss_avg_mb'],
                rss_max_mb=gc['rss_max_mb'], p99_ms=step['p99_ms'],
                lag_p99_ms=step['lag_p99_ms'], gen_cpu_pct=step['gen_cpu_pct'])


if __name__ == '__main__':
    rows = [summarize(name) for name in sys.argv[1:]]
    if not rows:
        raise SystemExit('用法：summarize-o1.py o1-gogc100 o1-gogc400')
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
