import hashlib
import json
import math
import re
import statistics
from time import perf_counter
from app.tracing.sanitize import TraceSanitizer, redact_text

STOP = set('what where when who is are the a an our for of to and in does do did was it at before now'.split())


def tokens(text):
    return [word for word in re.findall(r"[a-z0-9_]+", text.lower()) if word not in STOP]


def fixture_vector(text):
    """Reproducible lexical hash vectors, explicitly not neural semantic embeddings."""
    vector = [0.0] * 768
    for word in tokens(text):
        index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], 'big') % len(vector)
        vector[index] += 1.0
    norm = math.sqrt(sum(value*value for value in vector)) or 1.0
    return [value/norm for value in vector]


def load_dataset(path):
    dataset = json.loads(path.read_text(encoding='utf-8'))
    if dataset.get('schema_version') != '1.0' or not dataset.get('synthetic'):
        raise ValueError('Use the versioned synthetic evaluation dataset.')
    records = {record['id']: record for record in dataset['records']}
    if len(records) != len(dataset['records']) or len(dataset['cases']) < 30:
        raise ValueError('Dataset needs unique records and at least 30 cases.')
    if len({case['organization_id'] for case in dataset['cases']}) < 2:
        raise ValueError('Dataset must cover two organizations.')
    for case in dataset['cases']:
        for item_id in case['gold_evidence_ids']:
            if item_id not in records or records[item_id]['organization_id'] != case['organization_id'] or records[item_id]['permission'] not in case['allowed_scopes']:
                raise ValueError('Gold evidence must belong to the case organization and access scope.')
    return dataset


class OfflineBackend:
    name = 'offline_reference'
    def __init__(self, records):
        self.records = {row['id']: row for row in records}
        self.vectors = {row['id']: fixture_vector(row['content']) for row in records}

    def search(self, case, strategy, k):
        query = fixture_vector(case['question'])
        words = set(tokens(case['question']))
        permitted = [row for row in self.records.values() if row['organization_id'] == case['organization_id'] and row['permission'] in case['allowed_scopes']]
        dense = sorted(((sum(a*b for a,b in zip(query,self.vectors[row['id']])),row['id']) for row in permitted), key=lambda item:(-item[0],item[1]))
        dense = [item for item in dense if item[0] >= .15]
        if strategy == 'vector_only':
            return [{'item_id': key, 'dense_similarity': score, 'lexical_score': None, 'rrf_score': None} for score,key in dense[:k]]
        lexical = sorted(((len(words.intersection(tokens(row['content']))),row['id']) for row in permitted), key=lambda item:(-item[0],item[1]))
        lexical = [item for item in lexical if item[0] > 0]
        dense_rank = {key: rank for rank,(_,key) in enumerate(dense,1)}
        lexical_rank = {key: rank for rank,(_,key) in enumerate(lexical,1)}
        scores = {key:(1/(60+dense_rank[key]) if key in dense_rank else 0)+(1/(60+lexical_rank[key]) if key in lexical_rank else 0) for key in dense_rank.keys() | lexical_rank.keys()}
        return [{'item_id':key,'dense_similarity':dict((key,value) for value,key in dense).get(key),
                 'lexical_score':dict((key,value) for value,key in lexical).get(key), 'rrf_score':scores[key]}
                for key in sorted(scores,key=lambda key:(-scores[key],key))[:k]]

    def close(self):
        pass


def extractive_answer(question, results, records):
    """A labelled deterministic baseline, not a substitute for real-model evaluation.

No gold IDs, expected facts or case categories are consulted by this baseline.
"""
    words = set(tokens(question))
    candidates = []
    for result in results:
        record = records[result['item_id']]
        text = record['content']
        # Source text cannot authorize an operation. This baseline executes no tools.
        if re.search(r'ignore all|reveal .*keys?|system prompt|execute !',text,re.I):
            continue
        overlap = len(words.intersection(tokens(text)))
        if overlap:
            candidates.append((overlap,record))
    if not candidates:
        return '', []
    # Require question-specific evidence, rather than guessing from a project name.
    substantive = words - {'internal','confidential','amount','decision','current','earlier','latest'}
    candidates = [(score,row) for score,row in candidates if len(substantive.intersection(tokens(row['content']))) >= min(2,len(substantive))]
    if not candidates:
        return '', []
    if 'earlier' in words or 'current' in words or 'latest' in words:
        decisions = [(score,row) for score,row in candidates if row.get('decision_key')]
        if decisions:
            decisions.sort(key=lambda pair:pair[1]['timestamp'], reverse='earlier' not in words)
            row = decisions[0][1]
            return redact_text(row['content']), [row['id']]
    row = sorted(candidates,key=lambda pair:(-pair[0],pair[1]['id']))[0][1]
    return redact_text(row['content']), [row['id']]


def percentile95(values):
    return sorted(values)[max(0,math.ceil(.95*len(values))-1)] if values else 0


def evaluate(dataset, backend, *, k=4):
    records = {row['id']:row for row in dataset['records']}
    report = {'schema_version':'1.0','backend':backend.name,'embedding_source':'deterministic_lexical_hash_768',
              'generation':'deterministic_extractive_baseline','top_k':k,'strategies':{},'security_violations':0,'failures':[],
              'limitations':['Synthetic corpus; no real-provider inference is measured.',
                             'Offline lexical overlap is not PostgreSQL full-text ranking.',
                             'Prompt-injection checks cover defined boundaries; they are not a universal model robustness guarantee.']}
    sanitizer = TraceSanitizer()
    for strategy in ('vector_only','hybrid'):
        details=[]; recalls=[]; ranks=[]; hits=[]; latencies=[]; generation_latencies=[]; correct_citations=0; citation_count=0; abstentions=0; supported=0
        for case in dataset['cases']:
            start=perf_counter(); result=backend.search(case,strategy,k); retrieval_ms=(perf_counter()-start)*1000
            start=perf_counter(); answer,citations=extractive_answer(case['question'],result,records); generation_ms=(perf_counter()-start)*1000
            selected=[item['item_id'] for item in result]; gold=set(case['gold_evidence_ids'])
            violation=any(records[key]['organization_id']!=case['organization_id'] or records[key]['permission'] not in case['allowed_scopes'] for key in selected)
            report['security_violations'] += int(violation)
            if gold:
                recalls.append(len(gold.intersection(selected))/len(gold))
                rank=next((rank for rank,key in enumerate(selected,1) if key in gold),None)
                ranks.append(1/rank if rank else 0); hits.append(int(rank is not None))
                supported += int(bool(case.get('expected_fact')) and case['expected_fact'].lower() in answer.lower())
            correct_citations += len(set(citations).intersection(gold)); citation_count += len(citations)
            abstention_correct=bool(answer)==bool(gold)
            abstentions += int(abstention_correct); latencies.append(retrieval_ms); generation_latencies.append(generation_ms)
            reasons=[]
            if not abstention_correct: reasons.append('unanswerable_answered' if not gold else 'answerable_abstained')
            if gold and not gold.issubset(selected): reasons.append('gold_evidence_missing')
            if gold and case.get('expected_fact') and case['expected_fact'].lower() not in answer.lower(): reasons.append('expected_fact_missing')
            if reasons: report['failures'].append({'case_id':case['id'],'strategy':strategy,'reasons':reasons})
            details.append({'case_id':case['id'],'kind':case['kind'],'organization_id':case['organization_id'],
                            'selected_ids':selected,'cited_ids':citations,'abstained':not bool(answer),'abstention_correct':abstention_correct,
                            'fact_supported':case.get('expected_fact','') in answer if case.get('expected_fact') else None,
                            'retrieval_ms':round(retrieval_ms,4),'generation_ms':round(generation_ms,4),'scores':result})
        report['strategies'][strategy]={'recall_at_k':statistics.mean(recalls) if recalls else None,
                                      'hit_rate_at_k':statistics.mean(hits) if hits else None,
                                      'mrr':statistics.mean(ranks) if ranks else None,
                                      'citation_precision':correct_citations/citation_count if citation_count else None,
                                      'abstention_accuracy':abstentions/len(details),
                                      'expected_fact_accuracy':supported/len(recalls) if recalls else None,
                                      'retrieval_latency_mean_ms':statistics.mean(latencies),
                                      'retrieval_latency_p95_ms':percentile95(latencies),
                                      'generation_latency_mean_ms':statistics.mean(generation_latencies),
                                      'generation_latency_p95_ms':percentile95(generation_latencies),
                                      'input_tokens':None,'output_tokens':None,'token_reporting_type':'not_used',
                                      'estimated_cost_usd':None,'cases':details}
    return sanitizer.clean(report)


def markdown_report(report):
    lines=['# Thread V2 evaluation', '', f"Backend: `{report['backend']}`. Generation: `{report['generation']}`.", '',
           '| Strategy | Recall@k | MRR | Citation precision | Abstention accuracy | Retrieval p95 (ms) |',
           '| --- | --- | --- | --- | --- | --- |']
    for strategy,metrics in report['strategies'].items():
        values=[metrics[key] for key in ('recall_at_k','mrr','citation_precision','abstention_accuracy','retrieval_latency_p95_ms')]
        lines.append('| '+strategy+' | '+' | '.join(f'{value:.4f}' if value is not None else 'unavailable' for value in values)+' |')
    lines += ['',f"Security violations: {report['security_violations']}", '', '## Observed failures', '']
    lines += [f"- {item['case_id']} / {item['strategy']}: {', '.join(item['reasons'])}" for item in report['failures']] or ['No failures in the defined cases.']
    lines += ['', '## Limits', '']
    lines += ['- '+item for item in report['limitations']]
    return '\n'.join(lines)+'\n'
