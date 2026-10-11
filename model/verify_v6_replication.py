"""Compare an independent public-aggregate replication with the V6 snapshot.

Floating optimizers need not be bitwise identical. This check compares the
complete JSON and CSV output, not only the headline metrics. No private data
or identifying candidate rows are read.
"""
from pathlib import Path
import argparse
import json
import math

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / 'output/experiments/v6_statistical_inference_20261011'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('replication_dir', type=Path)
    args = parser.parse_args()
    if args.replication_dir.resolve() == REFERENCE.resolve():
        raise SystemExit('Use an independently generated output directory.')
    differences = []
    errors = []

    def compare(left, right, location):
        if isinstance(left, dict):
            if not isinstance(right, dict) or left.keys() != right.keys():
                errors.append(location + ': dictionary fields differ')
                return
            for key in left:
                compare(left[key], right[key], location + '/' + key)
        elif isinstance(left, list):
            if not isinstance(right, list) or len(left) != len(right):
                errors.append(location + ': list lengths differ')
                return
            for index, (a, b) in enumerate(zip(left, right)):
                compare(a, b, location + '/' + str(index))
        elif isinstance(left, (int, float)) and not isinstance(left, bool):
            if not isinstance(right, (int, float)) or isinstance(right, bool):
                errors.append(location + ': numeric type differs')
                return
            if not math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-4):
                errors.append(location + ': numeric tolerance exceeded')
            if left != right:
                differences.append((abs(left - right), location))
        elif left != right:
            errors.append(location + ': value differs')

    compare(json.loads((REFERENCE / 'summary.json').read_text(encoding='utf-8')),
            json.loads((args.replication_dir / 'summary.json').read_text(encoding='utf-8')),
            'summary')
    csv_count = 0
    for path in sorted(REFERENCE.glob('*.csv')):
        left = pd.read_csv(path)
        right = pd.read_csv(args.replication_dir / path.name)
        if list(left.columns) != list(right.columns) or left.shape != right.shape:
            errors.append(path.name + ': table structure differs')
            continue
        for column in left:
            a, b = left[column], right[column]
            if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                if not np.allclose(a, b, rtol=1e-6, atol=1e-4, equal_nan=True):
                    errors.append(path.name + '/' + column + ': numeric tolerance exceeded')
            elif not a.fillna('<missing>').equals(b.fillna('<missing>')):
                errors.append(path.name + '/' + column + ': nonnumeric value differs')
        csv_count += 1
    report = {'passed': not errors, 'csv_tables': csv_count,
              'absolute_tolerance': 1e-4, 'relative_tolerance': 1e-6,
              'largest_json_numeric_difference': max((d for d, _ in differences), default=0.),
              'errors': errors}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
