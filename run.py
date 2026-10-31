"""Run from the project directory: python run.py"""

import argparse
import subprocess
import sys
import time
import json
import hashlib
import platform
import csv

from pathlib import Path

import psutil

from common import s3, BUCKET, KEY, URI, dump, write_csv


def measured(command, log):
    metric = str(log) + '.metrics.json'

    with open(log, 'w', encoding='utf-8') as f:
        proc = subprocess.run(
            [
                command[0],
                'profile_worker.py',
                metric,
                *command[1:]
            ],
            stdout=f,
            stderr=subprocess.STDOUT
        )

    if proc.returncode:
        raise RuntimeError(
            f'Command failed ({proc.returncode}); see {log}'
        )

    m = json.loads(Path(metric).read_text())
    return m['seconds'], m['peak_rss_mib']


def load_counts(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return {
            tuple(json.loads(r['skills'])): int(r['count'])
            for r in csv.DictReader(f)
        }


def compare(left, right):
    details = []

    for k in (1, 2, 3):
        a = load_counts(Path(left) / f'counts_{k}.csv')
        b = load_counts(Path(right) / f'counts_{k}.csv')

        bad = [
            key
            for key in a.keys() | b.keys()
            if a.get(key) != b.get(key)
        ]

        details.append({
            'k': k,
            'keys': len(a),
            'mismatches': len(bad)
        })

        if bad:
            raise AssertionError(
                f'k={k}: {len(bad)} differences, examples: {bad[:5]}'
            )

    return details


def main():
    p = argparse.ArgumentParser()

    p.add_argument(
        '--local',
        action='store_true',
        help='Diagnostic run only, does not satisfy S3 requirement'
    )
    p.add_argument(
        '--csv',
        default='data/it_vacancies_2024.csv'
    )
    p.add_argument(
        '--skip-upload',
        action='store_true'
    )
    p.add_argument(
        '--runs',
        type=int,
        default=3
    )

    a = p.parse_args()

    if a.runs < 3:
        p.error('At least three runs required')

    result = Path('results_local' if a.local else 'results')
    result.mkdir(exist_ok=True)

    source = a.csv if a.local else URI

    sha = hashlib.sha256()

    with open(a.csv, 'rb') as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b''
        ):
            sha.update(block)

    digest = sha.hexdigest()
    client = None

    if not a.local:
        client = s3()

        buckets = {
            b['Name']
            for b in client.list_buckets()['Buckets']
        }

        if BUCKET not in buckets:
            client.create_bucket(Bucket=BUCKET)

        if not a.skip_upload:
            client.upload_file(
                a.csv,
                BUCKET,
                KEY,
                ExtraArgs={
                    'Metadata': {
                        'sha256': digest
                    }
                }
            )

        head = client.head_object(
            Bucket=BUCKET,
            Key=KEY
        )

        if (
            head['ContentLength'] != Path(a.csv).stat().st_size
            or head.get('Metadata', {}).get('sha256') != digest
        ):
            raise ValueError(
                'S3 object metadata/size does not match the input'
            )

        # Independently verify the bytes stored in S3, outside measured runs.
        body = client.get_object(
            Bucket=BUCKET,
            Key=KEY
        )['Body']

        remote = hashlib.sha256()

        try:
            for block in iter(
                lambda: body.read(1024 * 1024),
                b''
            ):
                remote.update(block)
        finally:
            body.close()

        if remote.hexdigest() != digest:
            raise ValueError('S3 SHA256 mismatch')

        dump(
            result / 'object.json',
            {
                'bucket': BUCKET,
                'key': KEY,
                'bytes': head['ContentLength'],
                'sha256': digest,
                'download_verified': True
            }
        )

        # Install outside timed runs; LOAD/import/startup remain timed for both methods.
        from common import connect

        connect(source).close()

    metrics = []
    checks = []

    for attempt in range(1, a.runs + 1):
        for method, script in [
            ('mapreduce', 'mapreduce.py'),
            ('duckdb', 'duck_query.py')
        ]:
            out = result / f'{method}_{attempt}'

            command = [
                sys.executable,
                script,
                '--source',
                source,
                '--out',
                str(out)
            ]

            seconds, mib = measured(
                command,
                result / f'{method}_{attempt}.log'
            )

            metrics.append([
                method,
                attempt,
                seconds,
                mib
            ])

            print(
                method,
                attempt,
                round(seconds, 3),
                round(mib, 1),
                flush=True
            )

        checks.append(
            compare(
                result / f'mapreduce_{attempt}',
                result / f'duckdb_{attempt}'
            )
        )

        if attempt > 1:
            compare(
                result / 'mapreduce_1',
                result / f'mapreduce_{attempt}'
            )

    # A real task exception is raised in a worker,
    # then retried and reduced exactly once.
    measured(
        [
            sys.executable,
            'mapreduce.py',
            '--source',
            source,
            '--out',
            str(result / 'failure'),
            '--inject-failure'
        ],
        result / 'failure.log'
    )

    compare(
        result / 'mapreduce_1',
        result / 'failure'
    )

    if json.loads(
        (result / 'failure/summary.json').read_text()
    )['retries'] != 1:
        raise AssertionError('Retry not exercised')

    dump(
        result / 'verification.json',
        {
            'full_count_tables_equal': True,
            'runs': checks,
            'mapper_exception_recovery': True,
            'failure_scope': (
                'task exception; not a killed process '
                'or broken process pool'
            )
        }
    )

    write_csv(
        result / 'profile.csv',
        [
            'method',
            'attempt',
            'seconds',
            'peak_rss_mib'
        ],
        metrics
    )

    subprocess.run(
        [
            sys.executable,
            'analyze.py',
            '--source',
            source,
            '--out',
            str(result / 'analysis')
        ],
        check=True
    )

    dump(
        result / 'environment.json',
        {
            'platform': platform.platform(),
            'python': sys.version,
            'logical_cpus': __import__('os').cpu_count(),
            'source': source,
            'sha256': digest,
            'local_diagnostic_only': a.local,
            'measurement': (
                'wall time within wrapper incl imports+read+compute+local output; '
                'memory metric recorded in *.metrics.json; RustFS excluded'
            ),
            'commands': (
                'see run.py; 2 workers / 2 DuckDB threads; '
                'chunk=2000 CSV records'
            )
        }
    )

    if client:
        for path in sorted(result.rglob('*')):
            if path.is_file():
                client.upload_file(
                    str(path),
                    BUCKET,
                    'lab3/' + str(
                        path.relative_to(result)
                    ).replace('\\', '/')
                )

        objects = []

        for page in client.get_paginator(
            'list_objects_v2'
        ).paginate(Bucket=BUCKET):
            objects.extend(
                {
                    'key': x['Key'],
                    'bytes': x['Size']
                }
                for x in page.get('Contents', [])
            )

        dump(
            result / 'bucket_listing.json',
            objects
        )

    print('Full equality verified; results:', result)


if __name__ == '__main__':
    main()
