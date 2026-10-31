import argparse
import json
from pathlib import Path

from common import connect, quote, write_csv, dump, URI


def run(source, out):
    c = connect(source)

    sql = Path(__file__).with_name('queries.sql').read_text(
        encoding='utf-8'
    )
    c.execute(sql.replace('{source}', quote(source)))

    duplicates = c.execute(
        "SELECT count(*) - count(DISTINCT source || ':' || vacancy_id) FROM raw"
    ).fetchone()[0]

    if duplicates:
        raise ValueError(
            'Repeated vacancy ids: choose a snapshot/deduplication rule first'
        )

    Path(out).mkdir(parents=True, exist_ok=True)

    unique = []
    occurrences = []

    for k, table, cols in [
        (1, 'singles', 'a'),
        (2, 'pairs', 'a,b'),
        (3, 'triples', 'a,b,c')
    ]:
        result = c.execute(
            f'SELECT {cols}, count(*) '
            f'FROM {table} '
            f'GROUP BY {cols} '
            f'ORDER BY {cols}'
        ).fetchall()

        rows = [
            (json.dumps(list(r[:-1]), ensure_ascii=False), r[-1])
            for r in result
        ]

        write_csv(
            Path(out) / f'counts_{k}.csv',
            ['skills', 'count'],
            rows
        )

        unique.append(len(result))
        occurrences.append(sum(r[-1] for r in result))

    summary = {
        'source': source,
        'rows': c.execute(
            'SELECT count(*) FROM raw'
        ).fetchone()[0],
        'selected': c.execute(
            'SELECT count(*) FROM mobile'
        ).fetchone()[0],
        'with_skills': c.execute(
            'SELECT count(*) FROM mobile WHERE len(skills)>0'
        ).fetchone()[0],
        'max_skills': c.execute(
            'SELECT max(len(skills)) FROM mobile'
        ).fetchone()[0],
        'unique': unique,
        'occurrences': occurrences,
        'duplicate_ids': duplicates
    }

    dump(Path(out) / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False))

    c.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', default=URI)
    p.add_argument('--out', default='results/duckdb')

    a = p.parse_args()
    run(a.source, a.out)
