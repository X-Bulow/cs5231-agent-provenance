"""Independent raw-byte replay, chronology and graph/file-version audit for v2."""
import hashlib
import json
import sys
from datetime import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

from v2_batch import ROOT,HERE,OUT,SHORT,load,save,sha,snapshot,verify
sys.path.insert(0,str(ROOT/'provenance'))
from trajectory import load_run
from build_graph import GraphBuilder,build_run,validate,write_graph
from runs import select_runs
from render import render_graph,ancestors

def digest(data):return hashlib.sha256(data).hexdigest()

def initial_bytes(run):
    baseline=load(run/'baseline.json'); scenario=load(run/'scenario.json')
    values={}
    for path,expected in baseline.items():
        if path in scenario['overrides']:
            content=scenario['overrides'][path].encode()
        else:
            source=ROOT/'artifact'/('skills/'+path[len('.agents/skills/'):] if path.startswith('.agents/skills/') else 'workload/'+path)
            if not source.exists():source=run/'workspace'/path
            content=source.read_bytes()
        assert digest(content)==expected,(run.name,path,'initial bytes mismatch')
        values[path]=content
    return values

def replay(t,values):
    observations=[]
    for c in t.calls:
        if c.status!='completed':continue
        if c.index in t.delegated:
            observations += replay(t.delegated[c.index],values)
        if c.tool not in ('edit','write'):continue
        path=c.input.get('filePath');raw=c.raw_input
        if not path:continue
        before=digest(values[path]) if path in values else None
        if c.tool=='write':values[path]=raw['content'].encode()
        else:
            old=raw['oldString'].encode();new=raw['newString'].encode()
            assert path in values and old in values[path],(t.session_id,c.index,'edit precondition')
            assert raw.get('replaceAll') or values[path].count(old)==1,(t.session_id,c.index,'ambiguous edit')
            values[path]=values[path].replace(old,new,-1 if raw.get('replaceAll') else 1)
        observations.append({'session':t.session_id,'call':c.index,'tool':c.tool,'path':path,'before':before,'after':digest(values[path])})
    return observations

def main():
    protocol=verify()
    assert sha(OUT/'capture/protocol.json')==load(OUT/'capture/preflight.json')['protocol_sha256']
    executions=[];profiles=[]
    for scheduled in protocol['runs']:
        name='run-'+scheduled['run'];run=ROOT/'artifact/runs'/name
        execution=load(run/'execution.json');env=load(OUT/(name+'-environment.json'))
        assert datetime.fromisoformat(protocol['created_at'])<datetime.fromisoformat(execution['started_at'])
        assert execution['model']==protocol['model'] and execution['timeout_seconds']==600 and execution['max_segments']==4
        assert env['scenario']==scheduled['condition'] and load(run/'scenario.json')['scenario']==scheduled['condition']
        assert load(run/'baseline.json')==protocol['baseline_by_condition'][scheduled['condition']]
        assert sha(run/'prompt.txt')==protocol['prompt_sha256']
        profile=OUT/'capture/sandbox-profiles'/('v2-'+name+'.sb')
        assert sha(profile)==env['sandbox_sha256']
        profiles.append(profile.read_text().replace(str(SHORT/name/'workspace'),'WORKSPACE'))
        for segment in execution['segments']:
            directory=run/'segments'/f"{segment['index']:02d}"
            invocation=load(directory/'invocation.json')['command']
            assert invocation[invocation.index('--model')+1]==protocol['model']
            assert invocation[invocation.index('--dir')+1]==str(SHORT/name/'workspace')
            if segment['index']:
                assert invocation[invocation.index('--session')+1]==execution['session_id']
                assert invocation[-1]==execution['continuation_text']
            exported=load(directory/'session.json')
            assert exported['info']['id']==execution['session_id']
            assert sum(m['info']['role']=='user' for m in exported['messages'])==segment['index']+1
        executions.append(execution)
    assert len(set(profiles))==1,'OS boundaries differ'
    for previous,current_execution in zip(executions,executions[1:]):
        assert datetime.fromisoformat(previous['ended_at'])<=datetime.fromisoformat(current_execution['started_at'])
    selection=select_runs(ROOT/'artifact/runs')
    assert len(selection.graph_runs)==10 and not selection.excluded and not selection.ungraphable
    figures=ROOT/'figures/v2-d7';figures.mkdir(exist_ok=True)
    per_run=[]
    formal={'run-'+r['run'] for r in protocol['runs']}
    for run in selection.graph_runs:
        t=load_run(run);g,notes=build_run(run)
        assert not validate(g)
        nodes={n['id']:n for n in g['nodes']}
        assert [(n['index'],n['call_id'],n['status']) for n in g['nodes'] if n['kind']=='call']==[(c.index,c.call_id,c.status) for c in t.calls]
        assert all(nodes[f'O:result:{c.index}']['content']==c.output for c in t.calls)
        for u in t.user_messages[1:]:
            node=nodes[f'O:user:{u.index}']
            assert node['content']==u.text and node['before_turn']==u.before_turn
            targets=[e['dst'] for e in g['edges'] if e['src']==node['id']]
            assert targets==([f'T:{u.before_turn}'] if u.before_turn<=len(t.turns) else [])
            for turn in t.turns[:u.before_turn-1]:
                assert node['id'] not in ancestors(g,f'T:{turn.index}'),(run.name,'future user ancestry')
        for e in g['edges']:
            for call,other in ((nodes[e['src']],nodes[e['dst']]),(nodes[e['dst']],nodes[e['src']])):
                if call['kind']=='call' and other['kind']=='file':
                    assert call['status']=='completed' and call['tool']!='invalid'
        baseline=load(run/'baseline.json')
        early=GraphBuilder(t,baseline,changes=None).build();early_nodes={n['id']:n for n in early['nodes']}
        checks=[]
        for change in load(run/'check.json')['changes']:
            versions=[n for n in g['nodes'] if n['kind']=='file' and n['path']==change['path']]
            assert versions,(run.name,change['path'],'missing version')
            last=max(versions,key=lambda n:n['version'])
            writers=[e for e in g['edges'] if e['rel']=='WRITE' and e['dst']==last['id']]
            assert writers and last['sha256']==change['after']
            known=early_nodes.get(last['id'],{}).get('sha256')
            assert known is None or known==change['after']
            checks.append({'path':change['path'],'last_version':last['id'],'writers':writers,
                'hash_support':'known_before_final_reconciliation' if known is not None else 'filled_from_final_check'})
        assert not [n for n in notes if not n.startswith('C:')],(run.name,notes)
        write_graph(g,ROOT/'graphs'/f'{run.name}.json')
        if run.name in formal:
            values=initial_bytes(run);observations=replay(t,values)
            observed={p:digest(b) for p,b in values.items()}
            expected=baseline.copy()
            for c in load(run/'check.json')['changes']:
                if c['after'] is None:expected.pop(c['path'],None)
                else:expected[c['path']]=c['after']
            assert observed==expected,(run.name,'raw-byte replay disagrees with final workspace')
            save(OUT/(run.name+'-raw-byte-replay.json'),{'operations':observations,'final_hashes':observed,'independent_of_check_until_comparison':True})
            svg=render_graph(g)
            ET.fromstring(svg)
            (figures/(run.name+'.svg')).write_text(svg)
            for p in load(run/'check.json')['protected_paths_changed']:
                anchor=next(n['id'] for n in g['nodes'] if n['kind']=='file' and n['path']==p and n['version']==1)
                svg=render_graph(g,ancestors_of=anchor)
                ET.fromstring(svg)
                (figures/(run.name+'-protected.svg')).write_text(svg)
            for parent_call,child in t.delegated.items():
                child_values=initial_bytes(run);ops=replay(child,child_values)
                child_changes={p:(baseline.get(p),digest(content)) for p,content in child_values.items() if baseline.get(p)!=digest(content)}
                child_graph=GraphBuilder(child,baseline,child_changes).build()
                child_graph['run']=run.name+'-child'
                assert not validate(child_graph)
                write_graph(child_graph,ROOT/'graphs'/f'{run.name}-child.json')
                (figures/(run.name+'-child.svg')).write_text(render_graph(child_graph))
                save(OUT/(run.name+'-child-replay.json'),{'parent_call':parent_call,'session_id':child.session_id,'operations':ops,'changes_from_replay':child_changes,'hash_support':'Full raw write/edit replay, not check.json. Child event stream unavailable.'})
        per_run.append({'run':run.name,'schema_version':g['schema_version'],'nodes':len(g['nodes']),'edges':len(g['edges']),
            'user_messages':len(t.user_messages),'user_boundaries':[u.before_turn for u in t.user_messages],
            'delegated_sessions':[c.session_id for c in t.delegated.values()],
            'file_versions':checks,'notes':notes,
            'graph_sha256':sha(ROOT/'graphs'/f'{run.name}.json')})
    save(OUT/'b1-b2-verification.json',{'status':'passed','scope':'D7 formal runs 030-039 only','graphable_runs':10,'runs':per_run,
        'formal_raw_byte_replays':10,'figures':snapshot(figures),
        'frozen_protocol_precedes_all_starts':True,'preallocated_order_verified':True,
        'same_normalized_sandbox_all_formal_runs':True,'segment_native_identity_and_user_counts_verified':True,
        'implementation_sha256':{p.relative_to(ROOT).as_posix():sha(p) for folder in (ROOT/'provenance',) for p in sorted(folder.glob('*.py'))},
        'limitations':['039 child native export available, independent child event stream unavailable.',
                      'Parent task edges summarize verified child operations and remain inferred.',
                      'Hash from final check is labelled separately from raw-byte replay and literal-write hashes.',
                      'Shell inference and graph ancestry do not establish causal influence.']})
    print(json.dumps({'status':'passed','graphs':10,'supplemental_child_graphs':1,'formal_raw_byte_replays':10,'figures':len(snapshot(figures))}))


if __name__=='__main__':main()
