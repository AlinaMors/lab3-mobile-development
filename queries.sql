
-- Фильтрация вакансий для варианта 9
CREATE TABLE raw AS
SELECT *
FROM read_csv(
    {source},
    header = true,
    all_varchar = true
);

CREATE TABLE mobile AS
SELECT
    source || ':' || vacancy_id AS vid,
    name,
    area,
    currency,
    gross,
    try_cast(salary_from AS DOUBLE) AS lo,
    try_cast(salary_to AS DOUBLE) AS hi,
    list_sort(
        list_distinct(
            list_filter(
                list_transform(
                    string_split(coalesce(key_skills, ''), ';'),
                    lambda x: lower(trim(x))
                ),
                lambda x: x <> ''
            )
        )
    ) AS skills
FROM raw
WHERE role = 'Программист, разработчик'
    AND regexp_matches(
        lower(name),
        '(^|[^a-zа-яё])(android|ios|flutter|mobile|мобильн[а-яё]*)([^a-zа-яё]|$)|react\s+native|kotlin\s+multiplatform'
    );

-- Подготовка зарплат для сравнения
ALTER TABLE mobile
ADD COLUMN salary DOUBLE;

UPDATE mobile
SET salary = CASE
    WHEN currency = 'RUR'
        AND gross = 'false'
        AND (lo IS NULL OR lo > 0)
        AND (hi IS NULL OR hi > 0)
        AND (lo IS NULL OR hi IS NULL OR lo <= hi)
    THEN
        CASE
            WHEN lo IS NOT NULL AND hi IS NOT NULL
                THEN (lo + hi) / 2
            ELSE coalesce(lo, hi)
        END
END;

-- Отдельные навыки
CREATE TABLE singles AS
SELECT
    vid,
    area,
    salary,
    unnest(skills) AS a
FROM mobile;

-- Пары навыков
CREATE TABLE pairs AS
SELECT
    a.vid,
    a.area,
    a.salary,
    a.a,
    b.a AS b
FROM singles a
JOIN singles b
    ON a.vid = b.vid
    AND a.a < b.a;

-- Тройки навыков
CREATE TABLE triples AS
SELECT
    p.*,
    s.a AS c
FROM pairs p
JOIN singles s
    ON p.vid = s.vid
    AND p.b < s.a;
