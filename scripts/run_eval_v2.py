"""Default run is offline and never reads application memory or provider keys."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.evaluation.runner import OfflineBackend,load_dataset,evaluate,markdown_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,default=ROOT/'backend/tests/fixtures/eval_v2_dataset.json')
    parser.add_argument('--report',type=Path,default=ROOT/'eval_v2_report.json')
    parser.add_argument('--backend',choices=['offline','postgres'],default='offline')
    parser.add_argument('--db-url-env',default='THREAD_EVAL_DB_URL',help='Disposable test database URL environment variable; never pass a URL on the command line.')
    parser.add_argument('--top-k',type=int,default=4)
    args=parser.parse_args()
    if not 1<=args.top_k<=20:
        parser.error('--top-k must be between 1 and 20')
    backend=None
    try:
        dataset=load_dataset(args.dataset)
        if args.backend=='postgres':
            from app.evaluation.postgres import PostgresBackend
            url=os.environ.get(args.db_url_env)
            if not url:
                raise ValueError('Configure the disposable evaluation database environment variable first.')
            backend=PostgresBackend(url,dataset['records'])
        else:
            backend=OfflineBackend(dataset['records'])
        report=evaluate(dataset,backend,k=args.top_k)
        report['dataset_sha256']=hashlib.sha256(args.dataset.read_bytes()).hexdigest()
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        markdown=markdown_report(report)
        args.report.with_suffix('.md').write_text(markdown,encoding='utf-8')
        print(markdown)
        return 1 if report['security_violations'] else 0
    except Exception:
        print('Evaluation failed. Check the synthetic dataset and, for postgres mode, the disposable database and pgvector installation. Connection details are withheld.',file=sys.stderr)
        return 2
    finally:
        if backend:
            try:
                backend.close()
            except Exception:
                print('Evaluation cleanup failed. Check the disposable evaluation schema; connection details are withheld.',file=sys.stderr)


if __name__=='__main__':
    raise SystemExit(main())
