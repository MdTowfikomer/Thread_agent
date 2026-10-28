"""Optional real pgvector/FTS benchmark in an isolated, disposable schema."""
import json
import uuid
from app.evaluation.runner import fixture_vector


class PostgresBackend:
    name='postgres_pgvector_fts'
    def __init__(self, url, records):
        import psycopg2
        from psycopg2 import sql
        self.connection=psycopg2.connect(url,connect_timeout=5,options='-c statement_timeout=15000')
        self.connection.autocommit=True
        self.schema='eval_v2_'+uuid.uuid4().hex
        self.created=False
        try:
            with self.connection.cursor() as cur:
                cur.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'")
                extension=cur.fetchone()
                if not extension:
                    raise ValueError('pgvector must already be installed in the disposable test database.')
                cur.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema))); self.created=True
                cur.execute(sql.SQL('SET search_path TO {}, {}').format(sql.Identifier(self.schema),sql.Identifier(extension[0])))
                cur.execute("CREATE TABLE corpus(id TEXT PRIMARY KEY,organization_id TEXT,permission TEXT,content TEXT,embedding vector(768),fts tsvector GENERATED ALWAYS AS (to_tsvector('english',content)) STORED)")
                for record in records:
                    vector=json.dumps(fixture_vector(record['content']))
                    cur.execute('INSERT INTO corpus(id,organization_id,permission,content,embedding) VALUES (%s,%s,%s,%s,%s::vector)',(record['id'],record['organization_id'],record['permission'],record['content'],vector))
        except Exception:
            self.close(); raise

    def search(self,case,strategy,k):
        vector=json.dumps(fixture_vector(case['question']))
        common="WITH permitted AS MATERIALIZED (SELECT * FROM corpus WHERE organization_id=%s AND permission=ANY(%s)) "
        with self.connection.cursor() as cur:
            if strategy=='vector_only':
                cur.execute(common+'SELECT id,1-(embedding <=> %s::vector) AS similarity FROM permitted WHERE 1-(embedding <=> %s::vector)>=0.15 ORDER BY embedding <=> %s::vector,id LIMIT %s',(case['organization_id'],case['allowed_scopes'],vector,vector,vector,k))
                return [{'item_id':row[0],'dense_similarity':float(row[1]),'lexical_score':None,'rrf_score':None} for row in cur.fetchall()]
            cur.execute(common+""",
                dense AS (SELECT id,1-(embedding <=> %s::vector) AS similarity,row_number() OVER (ORDER BY embedding <=> %s::vector,id) AS rank FROM permitted WHERE 1-(embedding <=> %s::vector)>=0.15),
                lexical AS (SELECT id,ts_rank_cd(fts,websearch_to_tsquery('english',%s)) AS score,row_number() OVER (ORDER BY ts_rank_cd(fts,websearch_to_tsquery('english',%s)) DESC,id) AS rank FROM permitted WHERE fts @@ websearch_to_tsquery('english',%s))
                SELECT coalesce(d.id,l.id),d.similarity,l.score,coalesce(1.0/(60+d.rank),0)+coalesce(1.0/(60+l.rank),0) AS rrf
                FROM dense d FULL OUTER JOIN lexical l ON d.id=l.id ORDER BY rrf DESC,coalesce(d.id,l.id) LIMIT %s
            """,(case['organization_id'],case['allowed_scopes'],vector,vector,vector,case['question'],case['question'],case['question'],k))
            return [{'item_id':row[0],'dense_similarity':float(row[1]) if row[1] is not None else None,'lexical_score':float(row[2]) if row[2] is not None else None,'rrf_score':float(row[3])} for row in cur.fetchall()]

    def close(self):
        from psycopg2 import sql
        if self.created:
            with self.connection.cursor() as cur:
                cur.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
            self.created=False
        self.connection.close()
