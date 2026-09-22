// Full Rust server -> EHDB bus -> Rust worker -> PostgreSQL validation.
// Requires the disposable cluster initialized by integration.mjs and local runtime.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const base='http://127.0.0.1:58082';
let checks=0;const executions=[];
async function post(route,body){const r=await fetch(base+route,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const v=await r.json();assert.ok(r.ok,JSON.stringify(v));return v;}
function sql(q){return execFileSync(process.env.PSQL||'psql',['-X','-At','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p','55439','-U','migration_owner','-d','adiona_validation','-c',q],{encoding:'utf8'}).trim();}
const postgresVersion=sql('SHOW server_version');
assert.ok(Number(sql('SHOW server_version_num'))>=190000&&Number(sql('SHOW server_version_num'))<200000,'PostgreSQL 19 server required');
async function credential(name,user){await post('/api/credentials',{name,type:'postgres',data:{db_host:'127.0.0.1',db_port:55439,db_name:'adiona_validation',db_user:user,db_password:''}});}
for(const f of fs.readdirSync(path.join(root,'playbooks')).filter(f=>f.endsWith('.yaml')&&f!=='reset.yaml'))await post('/api/catalog/register',{content:fs.readFileSync(path.join(root,'playbooks',f),'utf8')});
await credential('adiona_migrator','migration_owner');
async function run(name,request={},login='av_admin',expected='COMPLETED'){
 await credential('adiona_actor',login);
 const e=await post('/api/execute',{path:'adiona/v1/'+name,payload:{request}});
 const id=String(e.execution_id);assert.match(id,/^\d+$/);
 let status;
 for(let i=0;i<120;i++){
  const r=await fetch(base+'/api/executions/'+id+'/status');status=(await r.json()).status;
  if(['COMPLETED','FAILED','CANCELLED'].includes(status))break;
  await new Promise(resolve=>setTimeout(resolve,250));
 }
 assert.equal(status,expected,`${name}: execution ${id}`);
 const raw=sql(`SELECT result::text FROM noetl.event WHERE execution_id=${id} AND event_type='call.done' ORDER BY event_id DESC LIMIT 1`);
 const rows=raw?JSON.parse(raw)?.context?.result?.context?.data?.rows||[]:[];
 executions.push({playbook:name,execution_id:id,status});checks++;console.log('PASS runtime '+name+' '+status);
 return rows.map(x=>x.result??x);
}
await run('provision');await run('provision');
const types=await run('user_type_list');
const providerType=types.find(x=>x.user_type_name==='SERVICE_PROVIDER').user_type_id;
const customerType=types.find(x=>x.user_type_name==='CUSTOMER').user_type_id;
const user={user_type_id:customerType,email:'runtime@example.invalid',display_name:'Runtime Customer',first_name:'Runtime',last_name:'Customer'};
const u=(await run('user_upsert',user))[0];assert.equal((await run('user_upsert',user))[0].user_id,u.user_id);
const provider=Number(sql("SELECT user_id FROM adiona.principals WHERE db_role='av_provider'"));
const input={provider_id:provider,item_name:'Runtime catalog',price:2300,item_slug:'runtime-item'};
const item=(await run('item_upsert',input,'av_provider'))[0];assert.equal((await run('item_upsert',input,'av_provider'))[0].item_id,item.item_id);
await run('item_translation_upsert',{item_id:item.item_id,lang_code:'fr',item_name:'Runtime FR',item_desc:"O'Reilly {{ request }}",item_slug:'runtime-item-fr'},'av_provider');
const detail=(await run('item_get',{item_id:item.item_id},'av_customer'))[0];
assert.equal(detail.content.find(x=>x.lang_code==='fr').item_desc,"O'Reilly {{ request }}");
await run('item_update',{item_id:item.item_id,price:-1},'av_provider','FAILED');
assert.equal((await run('item_get',{item_id:item.item_id},'av_customer'))[0].price,2300);
await run('item_upsert',{...input,item_name:'Runtime rollback'},'av_provider','FAILED');
assert.equal(sql("SELECT count(*) FROM adiona.items WHERE item_name='Runtime rollback'"),'0');
await run('item_upsert',input,'av_other','FAILED');
await run('user_upsert',user,'av_customer','FAILED');
assert.equal((await run('user_get',{user_id:provider},'av_customer')).length,0);
await run('catalog_list',{lang:'fr'},'av_customer');
await run('item_translation_delete',{item_id:item.item_id,lang_code:'fr'},'av_provider');
await run('item_translation_delete',{item_id:item.item_id,lang_code:'en'},'av_provider');
await run('item_delete',{item_id:item.item_id},'av_provider');
assert.equal((await run('item_get',{item_id:item.item_id},'av_customer')).length,0);
await run('user_delete',{user_id:u.user_id});
assert.equal(sql(`SELECT count(*) FROM adiona.users WHERE user_id=${u.user_id}`),'0');
const report={postgres_version:postgresVersion,checks,registered:fs.readdirSync(path.join(root,'playbooks')).filter(f=>f.endsWith('.yaml')&&f!=='reset.yaml').length,executions};
fs.writeFileSync(path.join(root,'docs/runtime-results.json'),JSON.stringify(report,null,2)+'\n');
console.log(`PASS ${checks} real Rust runtime executions; including expected terminal failures.`);
