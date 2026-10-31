"""Streaming S3 -> CSV records -> bounded batches -> processes -> reduce."""
import csv, io, re, itertools, json, argparse
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from common import s3, URI, ROLE, PATTERN, dump, write_csv

@contextmanager
def records(source):
    if source.startswith('s3://'):
        bucket,key=source[5:].split('/',1)
        body=s3().get_object(Bucket=bucket,Key=key)['Body']
        stream=io.TextIOWrapper(body,encoding='utf-8-sig',newline='')
    else:
        stream=open(source,encoding='utf-8-sig',newline='')
    try:
        # CSV parser handles quoted commas and embedded newlines.
        yield csv.DictReader(stream)
    finally:
        stream.close()

def mapper(batch, fail=False):
    if fail:
        raise RuntimeError('Injected mapper exception before returning the result')
    counters=[Counter(),Counter(),Counter()]
    chosen=0; with_skills=0; max_skills=0
    for name,role,skills in batch:
        if role != ROLE or not re.search(PATTERN,name.lower()):
            continue
        chosen+=1
        skills=sorted(set(s.strip().lower() for s in skills.split(';') if s.strip()))
        with_skills+=bool(skills); max_skills=max(max_skills,len(skills))
        for k in (1,2,3):
            counters[k-1].update(itertools.combinations(skills,k))
    return counters,chosen,with_skills,max_skills

def run(source,out,workers=2,chunk=2000,inject=False):
    totals=[Counter(),Counter(),Counter()]; selected=0; with_skills=0; max_skills=0
    total_rows=0; retries=0; batches=0
    def consume(item,pool):
        nonlocal selected,with_skills,max_skills,retries
        future,batch=item
        try:
            result=future.result()
        except RuntimeError:
            # A failed batch has not been reduced. Retry once; second failure propagates.
            retries+=1; result=pool.submit(mapper,batch,False).result()
        counts,n,ns,m=result
        selected+=n; with_skills+=ns; max_skills=max(max_skills,m)
        for a,b in zip(totals,counts): a.update(b)
    with ProcessPoolExecutor(max_workers=workers) as pool, records(source) as rows:
        pending=deque(); batch=[]
        for row in rows:
            total_rows+=1
            batch.append((row['name'] or '',row['role'] or '',row['key_skills'] or ''))
            if len(batch)>=chunk:
                pending.append((pool.submit(mapper,batch,inject and batches==0),batch))
                batches+=1; batch=[]
                if len(pending)>=2*workers: consume(pending.popleft(),pool)
        if batch: pending.append((pool.submit(mapper,batch,inject and batches==0),batch))
        while pending: consume(pending.popleft(),pool)
    Path(out).mkdir(parents=True,exist_ok=True)
    for k,c in enumerate(totals,1):
        write_csv(Path(out)/f'counts_{k}.csv',['skills','count'],
                  [(json.dumps(key,ensure_ascii=False),v) for key,v in sorted(c.items())])
    summary={'source':source,'rows':total_rows,'selected':selected,'with_skills':with_skills,
             'max_skills':max_skills,'retries':retries,
             'unique':[len(c) for c in totals],'occurrences':[sum(c.values()) for c in totals]}
    dump(Path(out)/'summary.json',summary); print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',default=URI);p.add_argument('--out',default='results/mapreduce')
    p.add_argument('--workers',type=int,default=2);p.add_argument('--chunk',type=int,default=2000)
    p.add_argument('--inject-failure',action='store_true');a=p.parse_args()
    if a.workers<1 or a.chunk<1:p.error('workers and chunk must be positive')
    run(a.source,a.out,a.workers,a.chunk,a.inject_failure)
