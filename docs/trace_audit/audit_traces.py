"""Deterministic audit of bench audit.json traces. No LLM calls."""
import json,glob,csv,re,os,collections as C
R='/workspace/vw-bench/bench/results/traces/'
def num(x):
    try: return float(str(x).replace(',','').replace('$','').replace('%','').strip())
    except: return None
rows=[]
for f in sorted(glob.glob(R+'*-*/*/*.audit.json')):
    d=json.load(open(f)); run=f[len(R):].split('/')[0]
    bench='tatqa' if run.startswith('tatqa') else 'insightbench'
    split='train' if '-train-' in run else 'dev/eval'
    cfg=d['case'].get('config'); steps=d['steps']; types=[s['type'] for s in steps]
    decs=[s['decision'] for s in steps if isinstance(s.get('decision'),dict)]
    lc=d['llm_calls'] if isinstance(d.get('llm_calls'),list) else []
    tags=C.Counter(c.get('tag') for c in lc)
    conf=d['confidence']; sc=d['scores']; L=[]  # labels
    detc=conf.get('deterministic'); rec=conf.get('recomputed', conf.get('recomputed_base'))
    r=dict(run=run,bench=bench,split=split,config=cfg,item_id=d['case']['item_id'],path=f.replace('/workspace/vw-bench/',''),
           n_steps=len(steps),n_llm_calls=d['totals']['system'].get('calls'),conf_det=detc,conf_recomputed=rec)
    # ---- trace/logging bugs
    tb=[]
    if sc.get('failure') is None: tb.append('failure_field_null')
    if isinstance(detc,(int,float)) and isinstance(rec,(int,float)) and abs(detc-rec)>0.02: tb.append('confidence_formula_mismatch')
    roles={m['role'] for m in d['models']} if isinstance(d['models'],list) else set()
    if any(t.startswith(('verifier','v2_critic','v2_adjudicate')) for t in tags) and 'verifier' not in roles: tb.append('verifier_role_missing_in_models')
    if any(m['role']=='generator' and 'super' in m['model_id'] for m in d['models']) and cfg and cfg.endswith('vr'): tb.append('super_mislabelled_generator')
    if any(x.get('decision') is None for x in decs): tb.append('decision_name_null')
    if cfg and cfg.endswith('vr') and 'verify_retry_attempt' not in types: tb.append('verify_retry_steps_missing')
    if bench=='tatqa' and 'claim_gate' not in types: tb.append('claim_gate_step_missing')
    if d['case'].get('dataset_split')=='not_logged': tb.append('dataset_split_not_logged')
    if bench=='insightbench' and 'summary_judge' not in sc: tb.append('judge_score_missing')
    # ---- stage labels
    if bench=='tatqa':
        g=d['case']['eval_only']['gold']; fa=d['final_answer']; ok=sc.get('em')==1.0
        route=next((x['action'] for x in decs if x.get('decision')=='route'),'not_logged')
        gate=[x['action'] for x in decs if x.get('decision') in ('gate',None)]
        ga,pa=g.get('answer'),fa.get('answer'); gn,pn=num(ga if not isinstance(ga,list) else None),num(pa if not isinstance(pa,list) else None)
        r.update(score=sc.get('em'),f1=sc.get('f1'),route=route,gold_type=g.get('answer_type'),gold_scale=g.get('scale'),pred_scale=fa.get('scale'),gate_actions='|'.join(gate))
        if sc.get('em_raw')!=sc.get('em'): L.append('post_format_changed_score' + ('_helped' if (sc.get('em') or 0)>(sc.get('em_raw') or 0) else '_hurt'))
        calc=[s for s in steps if s['type']=='plan' and isinstance(s.get('outputs'),dict) and 'calc_history' in s['outputs']]
        if calc:
            acts=re.findall(r'ACTION \d+: (.*)',calc[0]['outputs']['calc_history'])
            if len(acts)>=2 and len(set(acts))==1: L.append('calc_loop_repeats_same_expr')
        if not ok:
            if g.get('answer_type')=='arithmetic' and route=='EVIDENCE': stage='route'; L.append('route_EVIDENCE_on_arithmetic')
            elif (g.get('scale') or '')!=(fa.get('scale') or ''): stage='writer_scale'; L.append('scale_mismatch')
            elif gn is not None and pn is not None and gn!=0 and abs(abs(pn)-abs(gn))<1e-6 and pn!=gn: stage='writer_sign'; L.append('sign_error')
            elif gn is not None and pn is not None and gn!=0 and abs(pn-gn)/abs(gn)<0.02: stage='post_format_rounding'; L.append('rounding_or_precision')
            elif gn is not None and pn is not None and gn!=0 and any(abs(pn/gn-k)<1e-3 for k in (100,0.01,1000,0.001,1e6,1e-6)): stage='writer_magnitude'; L.append('magnitude_x100_x1000')
            elif g.get('answer_type') in ('span','multi-span') : stage='writer_span'; L.append('wrong_span'+('_partial' if (sc.get('f1') or 0)>0 else ''))
            elif g.get('answer_type')=='count': stage='writer_count'; L.append('count_wrong')
            else: stage='calc_arithmetic'; L.append('arithmetic_wrong_operands_or_formula')
            if gate and gate[-1] in ('ACCEPT',) : L.append('gate_accepted_wrong_answer')
            if isinstance(detc,(int,float)) and detc>=0.7: L.append('overconfident_wrong(conf>=0.7)')
        else:
            stage='correct'
            if isinstance(detc,(int,float)) and detc<=0.3: L.append('underconfident_correct(conf<=0.3)')
            if gate and gate[-1]=='STOP': L.append('correct_but_gate_failed')
        if not sc.get('traceable',True): L.append('not_traceable')
        ex=sc.get('explain',{})
        if ex.get('citations') and ex.get('citations_valid',0)<ex['citations']: L.append('invalid_citations')
        if tags.get('v2_revise'): L.append('critic_revised')
    else:
        js=sc.get('summary_judge'); ok=(js or 0)>=0.5; ex=sc.get('explain',{})
        sqls=[s for s in steps if s['type']=='sql']; ev=d['evidence'] if isinstance(d['evidence'],list) else []
        errs=sum(1 for e in ev if e.get('is_error')); empty=sum(1 for e in ev if not e.get('is_error') and len(str(e.get('result','')).strip().split('\n'))<=1)
        rq=[x for x in decs if x.get('decision')=='requery']; rw=[x['action'] for x in decs if x.get('decision')=='rewrite']
        r.update(score=js,f1=sc.get('insight_rouge1'),route=next((x['action'] for x in decs if x.get('decision')=='depth'),''),
                 n_queries=len(ev),sql_errors=errs,empty_results=empty,gate_actions='|'.join(rw),faithfulness=ex.get('faithfulness'))
        if errs: L.append('sql_error_in_evidence')
        if empty: L.append('empty_sql_result')
        if any(x['action']=='STOP' and 'sufficient' in x['reason'] for x in rq) and (empty or errs): L.append('requery_STOP_sufficient_despite_empty_or_error')
        rep=[x for x in decs if x.get('decision')=='sql_repair']
        if any('same error' in x['reason'] for x in rep): L.append('sql_repair_same_error')
        if ex.get('numbers_unsupported'): L.append('unsupported_numbers_kept')
        if (ex.get('claims') or 0)==0: L.append('no_claims_kept')
        kept=[c for c in d['claims'] if c.get('gate_verdict')=='KEPT'] if isinstance(d['claims'],list) else []
        if kept and any(len(c.get('cited_evidence') or [])==0 for c in kept): L.append('kept_claim_without_citation')
        if js is None: stage='not_scored'
        elif ok: stage='correct'
        elif errs and errs>=len(ev)/2: stage='sql'
        elif empty and empty>=len(ev)/2: stage='retrieval_empty'
        elif (ex.get('claims') or 0)==0: stage='claim_gate_dropped_all'
        elif (ex.get('faithfulness') or 1)<0.5: stage='writer_unfaithful'
        else: stage='writer_wrong_insight(faithful_but_off_goal)'
        if isinstance(detc,(int,float)) and detc>=0.7 and js is not None and js<0.5: L.append('overconfident_wrong(conf>=0.7)')
        if tags.get('v2_cr_write'): L.append('critic_revised')
    r['stage']=stage; r['labels']='|'.join(L); r['trace_bugs']='|'.join(tb); rows.append(r)
keys=sorted({k for r in rows for k in r},key=lambda k:list(rows[0]).index(k) if k in rows[0] else 99)
with open(os.path.dirname(__file__)+'/trace_labels.csv','w',newline='') as fh:
    w=csv.DictWriter(fh,fieldnames=keys); w.writeheader(); w.writerows(rows)
json.dump(rows,open('/tmp/rows.json','w'))
print(len(rows))
