
import argparse
import json
from pathlib import Path

from common import connect, quote, write_csv, dump, URI


def run(source, out, min_n=10):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    c = connect(source)

    sql = Path(__file__).with_name('queries.sql').read_text(
        encoding='utf-8'
    )
    c.execute(sql.replace('{source}', quote(source)))

    def save(name, sql, args=None):
        cur = c.execute(sql, args or [])
        rows = cur.fetchall()

        write_csv(
            out / (name + '.csv'),
            [x[0] for x in cur.description],
            rows
        )
        return rows

    save(
        'selected_vacancies',
        '''
        SELECT
            vid, name, area, currency, gross,
            lo, hi, salary, skills
        FROM mobile
        ORDER BY vid
        '''
    )

    save(
        'salary_coverage',
        '''
        SELECT
            currency,
            gross,
            count(*) vacancies,
            count(salary) comparable
        FROM mobile
        GROUP BY currency, gross
        ORDER BY vacancies DESC
        '''
    )

    save(
        'skill_count_distribution',
        '''
        SELECT
            len(skills) n_skills,
            count(*) vacancies
        FROM mobile
        GROUP BY n_skills
        ORDER BY n_skills
        '''
    )

    regions = [
        r[0]
        for r in c.execute(
            '''
            SELECT area
            FROM mobile
            GROUP BY area
            ORDER BY count(*) DESC, area
            LIMIT 3
            '''
        ).fetchall()
    ]

    c.execute('CREATE TABLE chosen_regions(area VARCHAR)')
    c.executemany(
        'INSERT INTO chosen_regions VALUES (?)',
        [(x,) for x in regions]
    )

    save(
        'regions',
        '''
        SELECT
            area,
            count(*) vacancies,
            count(salary) salary_n,
            median(salary) median_net_rub,
            count(*) FILTER (WHERE len(skills) > 0) with_skills,
            avg(len(skills)) avg_skills
        FROM mobile
        JOIN chosen_regions USING(area)
        GROUP BY area
        ORDER BY vacancies DESC
        '''
    )

    c.execute(
        '''
        CREATE TABLE skill_stats AS
        SELECT
            a,
            count(*) n,
            count(salary) salary_n,
            median(salary) med
        FROM singles
        GROUP BY a
        '''
    )

    for k, table, cols in [
        (1, 'singles', 'a'),
        (2, 'pairs', 'a,b'),
        (3, 'triples', 'a,b,c')
    ]:
        save(
            f'region_stacks_{k}',
            f'''
            WITH agg AS (
                SELECT
                    area,
                    {cols},
                    count(*) n,
                    count(salary) salary_n,
                    median(salary) median_net_rub
                FROM {table}
                JOIN chosen_regions USING(area)
                GROUP BY area, {cols}
            )
            SELECT *
            FROM agg
            ORDER BY area, n DESC, {cols}
            '''
        )

    c.execute(
        '''
        CREATE TABLE pair_stats AS
        SELECT
            a,
            b,
            count(*) n,
            count(salary) salary_n,
            median(salary) med
        FROM pairs
        GROUP BY a, b
        '''
    )

    save(
        'pair_effects',
        f'''
        WITH base AS (
            SELECT
                p.*,
                CASE
                    WHEN x.n >= y.n THEN p.a
                    ELSE p.b
                END base_skill,
                CASE
                    WHEN x.n >= y.n THEN x.n
                    ELSE y.n
                END base_n,
                CASE
                    WHEN x.n >= y.n THEN x.salary_n
                    ELSE y.salary_n
                END base_salary_n,
                CASE
                    WHEN x.n >= y.n THEN x.med
                    ELSE y.med
                END base_median
            FROM pair_stats p
            JOIN skill_stats x ON p.a = x.a
            JOIN skill_stats y ON p.b = y.a
        )
        SELECT
            *,
            med - base_median delta_rub,
            100 * (med / base_median - 1) delta_pct
        FROM base
        WHERE salary_n >= {min_n}
            AND base_salary_n >= {min_n}
            AND base_median > 0
        ORDER BY delta_pct DESC, a, b
        '''
    )

    save(
        'triple_effects',
        f'''
        WITH ts AS (
            SELECT
                a,
                b,
                c,
                count(*) n,
                count(salary) salary_n,
                median(salary) med
            FROM triples
            GROUP BY a, b, c
        ),
        candidates AS (
            SELECT
                t.*,
                p.a base_a,
                p.b base_b,
                p.n base_n,
                p.salary_n base_salary_n,
                p.med base_median,
                row_number() OVER (
                    PARTITION BY t.a, t.b, t.c
                    ORDER BY p.n DESC, p.a, p.b
                ) choice
            FROM ts t
            JOIN pair_stats p
                ON (p.a = t.a AND p.b = t.b)
                OR (p.a = t.a AND p.b = t.c)
                OR (p.a = t.b AND p.b = t.c)
        )
        SELECT
            * EXCLUDE(choice),
            med - base_median delta_rub,
            100 * (med / base_median - 1) delta_pct
        FROM candidates
        WHERE choice = 1
            AND salary_n >= {min_n}
            AND base_salary_n >= {min_n}
            AND base_median > 0
        ORDER BY delta_pct DESC, a, b, c
        '''
    )

    config = {
        'regions': regions,
        'min_salary_n': min_n,
        'salary': 'RUR, gross=false; midpoint or available bound',
        'pair_base': (
            'most frequent skill (all selected vacancies); '
            'lexical tie break'
        ),
        'triple_base': (
            'most frequent contained pair (all selected vacancies); '
            'lexical tie break'
        )
    }

    dump(out / 'analysis_config.json', config)
    print('Analysis ready:', regions)


if __name__ == '__main__':
    p = argparse.ArgumentParser()

    p.add_argument('--source', default=URI)
    p.add_argument('--out', default='results/analysis')
    p.add_argument('--min-n', type=int, default=10)

    a = p.parse_args()
    run(a.source, a.out, a.min_n)
