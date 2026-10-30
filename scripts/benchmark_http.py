#!/usr/bin/env python3
"""Measure full HTTP ticket creation on loopback using synthetic inputs only."""
import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import uuid

import httpx
import numpy as np

TEXTS=[('ru','Синтетический пример: оскорблял меня в чате, есть запись.'),
       ('kk','Синтетикалық мысал: ойыншы мені балағаттады, скриншот бар.'),
       ('uz','Sunʼiy misol: o‘yinchi meni haqorat qildi, skrinshot bor.')]


async def measure(url,n,concurrency):
    limit=asyncio.Semaphore(concurrency)
    headers={'Authorization':'Bearer '+os.environ['API_TOKEN']} if os.getenv('API_TOKEN') else {}
    durations=[];statuses=Counter();modes=Counter();costs=[];unknown_cost=0
    run=uuid.uuid4().hex
    async with httpx.AsyncClient(base_url=url,headers=headers,timeout=30,trust_env=False) as client:
        health=await client.get('/api/health');health.raise_for_status();health=health.json()
        async def one(i):
            nonlocal unknown_cost
            lang,text=TEXTS[i%len(TEXTS)]
            async with limit:
                start=time.perf_counter()
                try:
                    response=await client.post('/api/tickets',json={'kind':'complaint','text':f'{text} Synthetic case {run}-{i}',
                        'server_lang':lang,'player_id':f'synthetic-{run}-{i}','attachments_count':1},
                        headers={'Idempotency-Key':f'benchmark-{run}-{i}'})
                    durations.append((time.perf_counter()-start)*1000);statuses[str(response.status_code)]+=1
                    if response.status_code==201:
                        d=response.json()['diagnostics'];modes[d['generation_mode']]+=1
                        if d['estimated_cost_usd'] is None:unknown_cost+=1
                        else:costs.append(d['estimated_cost_usd'])
                except httpx.RequestError:
                    durations.append((time.perf_counter()-start)*1000);statuses['transport_error']+=1
        start=time.perf_counter();await asyncio.gather(*(one(i) for i in range(n)))
        return {'synthetic_only':True,'sample_count':n,'concurrency':concurrency,'status_counts':dict(statuses),
                'generation_modes':dict(modes),'retrieval_mode':health['retrieval_mode'],'dense_loaded':health['local_encoder_loaded'],
                'elapsed_seconds':time.perf_counter()-start,'latency_ms':{'p50':float(np.percentile(durations,50)),
                'p95':float(np.percentile(durations,95)),'max':max(durations)},
                'known_external_api_cost_usd':sum(costs),'unknown_cost_successes':unknown_cost,
                'scope':'HTTP POST /api/tickets including queue waiting, NLP, retrieval, generation, SQLite and serialization',
                'limitations':['Warm server; startup and model loading excluded.','Synthetic load is not production traffic.',
                               'No quality/accuracy labels; infrastructure/compute cost not measured.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',default='http://127.0.0.1:8000')
    p.add_argument('--requests',type=int,default=60);p.add_argument('--concurrency',type=int,default=4);p.add_argument('--output',required=True)
    a=p.parse_args()
    if urlsplit(a.url).hostname not in {'127.0.0.1','localhost','::1'}:p.error('Only loopback targets are allowed')
    if not 1<=a.requests<=1000 or not 1<=a.concurrency<=32:p.error('requests 1..1000; concurrency 1..32')
    result=asyncio.run(measure(a.url,a.requests,a.concurrency))
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
