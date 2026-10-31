"""Portable benchmark wrapper. Linux: kernel peak RSS; Windows: sampled process tree."""
import sys,runpy,json,time,threading,platform
from pathlib import Path

def main():
    metric_path,script,*args=sys.argv[1:]
    started=time.perf_counter();peak=[0];stop=threading.Event()
    if sys.platform=='win32':
        import psutil
        root=psutil.Process()
        def sample():
            while not stop.is_set():
                rss=0
                for p in [root]+root.children(recursive=True):
                    try:rss+=p.memory_info().rss
                    except psutil.Error:pass
                peak[0]=max(peak[0],rss);stop.wait(.02)
        worker=threading.Thread(target=sample,daemon=True);worker.start()
    sys.argv=[script]+args
    runpy.run_path(script,run_name='__main__')
    elapsed=time.perf_counter()-started
    if sys.platform=='win32':
        stop.set();worker.join();mib=peak[0]/1024**2;kind='sampled process-tree RSS'
    else:
        import resource
        peak_rss=max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
        mib=peak_rss/(1024**2 if sys.platform=='darwin' else 1024)
        kind='kernel peak RSS of largest process; not sum of parallel workers'
    Path(metric_path).write_text(json.dumps({'seconds':elapsed,'peak_rss_mib':mib,'memory_metric':kind}),encoding='utf-8')
if __name__=='__main__':main()
