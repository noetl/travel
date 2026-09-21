"""Package-level static checks and HTTP contract harness; NOT the NoETL engine."""
import argparse, ast, json, re, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import urlparse
import yaml
ROOT=Path(__file__).resolve().parents[1]

def lookup(path,ctx):
    for part in path.split('.'): ctx=ctx[part]
    return ctx

def render(value,ctx):
    if isinstance(value,dict): return {k:render(v,ctx) for k,v in value.items()}
    if isinstance(value,list): return [render(v,ctx) for v in value]
    if not isinstance(value,str): return value
    match=re.fullmatch(r'{{\s*([\w.]+)\s*}}',value)
    if match: return lookup(match[1],ctx)
    return re.sub(r'{{\s*([\w.]+)\s*}}',lambda m:str(lookup(m[1],ctx)),value)

def condition(expr,ctx):
    match=re.fullmatch(r'([\w.]+)\s+(in|==)\s+(.+)',expr.removeprefix('{{').removesuffix('}}').strip())
    if not match: raise ValueError('Unsupported condition: '+expr)
    try: value=lookup(match[1],ctx)
    except KeyError: return False
    right=ast.literal_eval(match[3])
    return value in right if match[2]=='in' else value==right

def validate(path):
    data=yaml.safe_load(path.read_text())
    assert data['apiVersion']=='noetl.io/v2' and data['kind']=='Playbook'
    steps=data['workflow'];names=[s['step'] for s in steps]
    assert len(names)==len(set(names))
    assert 'start' in names
    assert data['executor']['spec']['entry_step'] in names
    for s in steps:
        tool=s['tool'];assert tool['kind'] in ('http','python')
        for arc in s.get('next',{}).get('arcs',[]): assert arc['step'] in names
        if tool['kind']=='http':
            assert tool['method']=='POST'
            assert tool['headers']['Idempotency-Key'].startswith('{{ request_key }}:')
            assert 'json' in tool and 'tenant_id' not in tool['json']
            assert tool['headers']['X-Demo-Principal'] in ('demo-staff','demo-worker')
        else: assert tool['code']=='result = payload\n'
    return data

def run(path,overrides=None):
    data=validate(path);ctx={**data['workload'],**(overrides or {}),'ctx':{}}
    url=urlparse(ctx['api_base'])
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost') or url.username or url.password:
        raise ValueError('Harness only permits the local development adapter')
    steps={s['step']:s for s in data['workflow']};name=data['executor']['spec']['entry_step']
    for _ in range(30):
        step=steps[name];tool=step['tool']
        if tool['kind']=='python': result=render(tool['input']['payload'],ctx)
        else:
            request=urllib.request.Request(render(tool['url'],ctx),data=json.dumps(render(tool['json'],ctx)).encode(),headers=render(tool['headers'],ctx),method='POST')
            attempts=0
            while True:
                try:
                    with urllib.request.urlopen(request,timeout=tool['timeout_seconds']) as response:
                        status=response.status;body=json.loads(response.read())
                except urllib.error.HTTPError as response:
                    status=response.code;body=json.loads(response.read())
                current={**ctx,'output':{'status':'ok' if 200<=status<300 else 'error','data':{'status_code':status,'data':body}}}
                for rule in tool['spec']['policy']['rules']:
                    if 'else' in rule: action=rule['else']['then'];break
                    if condition(rule['when'],current): action=rule['then'];break
                if action['do']=='fail': raise RuntimeError(f'{name}: HTTP {status}: {body}')
                if action['do']=='retry':
                    attempts+=1
                    if attempts>action['attempts']: raise RuntimeError(f'{name}: retry exhausted')
                    time.sleep(min(action['delay']*2**(attempts-1),2));continue
                for key,value in action.get('set',{}).items():
                    assert key.startswith('ctx.');ctx['ctx'][key[4:]]=render(value,current)
                result=body;break
        arcs=step.get('next',{}).get('arcs',[])
        if not arcs:return result
        assert len(arcs)==1;name=arcs[0]['step']
    raise RuntimeError('Step limit exceeded')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--demo',action='store_true');p.add_argument('--api-base',default='http://127.0.0.1:8099');p.add_argument('--request-key',default='demo-booking-001');args=p.parse_args()
    files=sorted((ROOT/'playbooks').glob('*.yaml'))
    for f in files:validate(f)
    print(f'{len(files)} playbooks passed package-level checks (not NoETL runtime validation).')
    if args.demo:print(json.dumps(run(ROOT/'playbooks'/'booking_demo.yaml',{'api_base':args.api_base,'request_key':args.request_key}),indent=2))
