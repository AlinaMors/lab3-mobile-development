import os, json, csv
from pathlib import Path
from urllib.parse import urlparse

BUCKET = 'hh-lake'
KEY = 'it_vacancies_2024.csv'
URI = f's3://{BUCKET}/{KEY}'
ROLE = 'Программист, разработчик'
PATTERN = r'(^|[^a-zа-яё])(android|ios|flutter|mobile|мобильн[а-яё]*)([^a-zа-яё]|$)|react\s+native|kotlin\s+multiplatform'

def s3():
    import boto3
    from botocore.config import Config
    return boto3.client('s3', endpoint_url=os.getenv('S3_ENDPOINT','http://127.0.0.1:9000'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID','rustfsadmin'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY','rustfsadmin'),
        region_name='us-east-1', config=Config(signature_version='s3v4',s3={'addressing_style':'path'}))

def quote(s):
    return "'" + str(s).replace("'", "''") + "'"

def connect(source):
    import duckdb
    c=duckdb.connect()
    c.execute("SET threads=2")
    c.execute("SET memory_limit='2GB'")
    if source.startswith('s3://'):
        c.execute('INSTALL httpfs; LOAD httpfs;')
        endpoint=urlparse(os.getenv('S3_ENDPOINT','http://127.0.0.1:9000'))
        c.execute(f"""CREATE SECRET (TYPE s3, KEY_ID {quote(os.getenv('AWS_ACCESS_KEY_ID','rustfsadmin'))},
        SECRET {quote(os.getenv('AWS_SECRET_ACCESS_KEY','rustfsadmin'))}, REGION 'us-east-1',
        ENDPOINT {quote(endpoint.netloc)}, URL_STYLE 'path', USE_SSL {str(endpoint.scheme=='https').lower()})""")
    return c

def dump(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def write_csv(path, headers, rows):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with open(path,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(headers); w.writerows(rows)
