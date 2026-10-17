"""Optional CSV export, adapted from Muneer Al-Shetri's full-log preparation.

Uses the same parser and schema as loading; no parallel parsing implementation.
"""
import argparse
import csv
from pathlib import Path

try:
    from .load_logs import COMMON, EXTRA, input_files, rows
except ImportError:
    from load_logs import COMMON, EXTRA, input_files, rows


def export(dataset, paths, destination):
    count = rejected = 0
    # Exclusive create protects previous exports from accidental replacement.
    with destination.open('x', encoding='utf-8', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=COMMON + EXTRA[dataset])
        writer.writeheader()
        for path in paths:
            for row in rows(dataset, path):
                writer.writerow(row)
                count += 1
                rejected += not row['parse_ok']
                if count % 500000 == 0:
                    print(f'Exported {dataset}: {count:,} rows', flush=True)
    return count, rejected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=Path('data/processed'))
    parser.add_argument('--dataset', choices=('all', 'bgl', 'openstack'), default='all')
    args = parser.parse_args()
    datasets = input_files(args.data_root, args.dataset)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for dataset in datasets:
        destination = args.output_dir / f'{dataset}_full.csv'
        if destination.exists():
            parser.error(f'Export already exists: {destination}. Choose another output directory.')
    for dataset, paths in datasets.items():
        destination = args.output_dir / f'{dataset}_full.csv'
        count, flagged = export(dataset, paths, destination)
        print(f'{destination}: {count:,} records, {flagged:,} flagged headers retained')
