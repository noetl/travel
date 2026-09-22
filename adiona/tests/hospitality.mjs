// Real PostgreSQL 19 tests; --runtime dispatches every playbook through Rust server/worker.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {execFileSync,spawn} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const runtime=process.argv.includes('--runtime');
const suffix=runtime?'runtime':'tool';
const binary=path.join(root,'tests/rust/target/debug/adiona-noetl-validation');
const executions=[];let passed=0;
// Ensure version 2's recorded digest describes its actual immutable DDL body.
const migration=fs.readFileSync(path.join(root,'playbooks/lodging_provision.yaml'),'utf8').split('\n').map(line=>line.startsWith('        ')?line.slice(8):line).join('\n');
const body= migration.slice(migration.indexOf('CREATE TABLE adiona.lodging_units'),migration.indexOf('\n INSERT INTO adiona_migrations.versions'));
assert.equal(createHash('sha256').update(body).digest('hex'),fs.readFileSync(path.join(root,'docs/migration-2-sha256.txt'),'utf8').trim(),'Migration 2 DDL digest mismatch');
function sql(q){return execFileSync(process.env.PSQL||'psql',['-X','-At','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p','55439','-U','migration_owner','-d','adiona_validation','-c',q],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();}
assert.ok(Number(sql('SHOW server_version_num'))>=190000&&Number(sql('SHOW server_version_num'))<200000);
// Refuse to operate on anything except the package's disposable local cluster.
assert.equal(fs.realpathSync(sql('SHOW data_directory')),fs.realpathSync(path.join(root,'.local/pgdata-19')));
async function post(route,body){const r=await fetch('http://127.0.0.1:58082'+route,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});const v=await r.json();assert.ok(r.ok,JSON.stringify(v));return v;}
if(runtime){
 for(const file of ['lodging_provision','lodging_unit_upsert','lodging_availability','reservation_hold','reservation_get','reservation_transition','reservation_release_expired','item_upsert'])await post('/api/catalog/register',{content:fs.readFileSync(path.join(root,'playbooks',file+'.yaml'),'utf8')});
}
async function call(name,request={},login='av_provider',attempt=0){
 if(runtime){
  const alias=name==='lodging_provision'?'adiona_migrator':'adiona_actor';
  await post('/api/credentials',{name:alias,type:'postgres',data:{db_host:'127.0.0.1',db_port:55439,db_name:'adiona_validation',db_user:login,db_password:''}});
  const e=await post('/api/execute',{path:'adiona/v1/'+name,payload:{request}});const id=String(e.execution_id);assert.match(id,/^\d+$/);
  let status;
  for(let i=0;i<160;i++){status=(await(await fetch('http://127.0.0.1:58082/api/executions/'+id+'/status')).json()).status;if(['COMPLETED','FAILED','CANCELLED'].includes(status))break;await new Promise(r=>setTimeout(r,250));}
  executions.push({playbook:name,execution_id:id,status});
  if(status!=='COMPLETED')throw Error('Runtime '+status+' '+name);
  const raw=sql(`SELECT result::text FROM noetl.event WHERE execution_id=${id} AND event_type='call.done' ORDER BY event_id DESC LIMIT 1`);
  return (JSON.parse(raw)?.context?.result?.context?.data?.rows||[]).map(r=>r.result??r);
 }
 try{return await new Promise((resolve,reject)=>{const child=spawn(binary,[path.join(root,'playbooks',name+'.yaml'),login,JSON.stringify(request)]);let out='',err='';child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);child.on('error',reject);child.on('close',(code,signal)=>code!==0?reject(Error(err||`Validation process exited with code ${code}, signal ${signal}`)):resolve((JSON.parse(out).rows||[]).map(r=>r.result??r)));});}
 catch(e){if(attempt<8&&/40001|40P01/.test(e.message)){await new Promise(resolve=>setTimeout(resolve,Math.min(250,10*2**attempt)+Math.random()*20));return call(name,request,login,attempt+1);}throw e;}
}
async function test(label,fn){await fn();passed++;console.log('PASS '+suffix+' '+label);}
async function fails(fn,pattern){await assert.rejects(fn,runtime?/Runtime FAILED/:pattern);}
const provider=sql("SELECT user_id FROM adiona.principals WHERE db_role='av_provider'");
const customer=sql("SELECT user_id FROM adiona.principals WHERE db_role='av_customer'");
await test('versioned provisioning is repeatable',async()=>{await call('lodging_provision',{},'migration_owner');await call('lodging_provision',{},'migration_owner');assert.equal(sql('SELECT count(*) FROM adiona_migrations.versions WHERE version=2'),'1');});
const item=(await call('item_upsert',{provider_id:provider,item_name:'Lodging '+suffix,item_slug:'lodging-'+suffix}))[0];
const input={provider_id:provider,item_id:item.item_id,unit_code:'101-'+suffix,capacity:2,nightly_rate:'12500',currency_code:'USD'};
const unit=(await call('lodging_unit_upsert',input))[0];
const stay={unit_id:unit.unit_id,guest_id:customer,idempotency_key:suffix+'-first',arrival:'2030-05-01',departure:'2030-05-04',guests:2};
const query={item_id:item.item_id,arrival:stay.arrival,departure:stay.departure,guests:2};
await test('room links to catalog and retries return same ID',async()=>assert.equal((await call('lodging_unit_upsert',input))[0].unit_id,unit.unit_id));
await test('availability quotes exact cents and nights',async()=>{const x=(await call('lodging_availability',query))[0];assert.equal(x.total_cents,'37500');assert.equal(x.nights,3);});
await test('invalid dates and capacities fail',async()=>{await fails(()=>call('lodging_availability',{...query,departure:query.arrival}),/finite dates/);await fails(()=>call('lodging_unit_upsert',{...input,capacity:0}),/check constraint/);await fails(()=>call('reservation_hold',{...stay,guests:3}),/capacity/);});
await test('customers and other providers cannot manage rooms',async()=>{await fails(()=>call('lodging_unit_upsert',input,'av_customer'),/not authorized/);await fails(()=>call('lodging_unit_upsert',input,'av_other'),/not authorized/);await fails(()=>call('lodging_availability',query,'av_customer'),/Staff role/);});
const hold=(await call('reservation_hold',stay))[0];
await test('hold snapshots price and blocks overlapping inventory',async()=>{assert.equal(hold.status,'held');assert.equal(hold.total_cents,'37500');assert.equal((await call('lodging_availability',query)).length,0);await fails(()=>call('reservation_hold',{...stay,idempotency_key:suffix+'-overlap'}),/exclusion constraint/);});
await test('retry preserves hold ID, expiry, version and quote',async()=>{await call('lodging_unit_upsert',{...input,nightly_rate:'15000'});const replay=(await call('reservation_hold',stay))[0];assert.equal(replay.reservation_id,hold.reservation_id);assert.equal(replay.expires_at,hold.expires_at);assert.equal(replay.version,1);assert.equal(replay.total_cents,'37500');});
await test('idempotency key payload mismatch fails atomically',async()=>{await fails(()=>call('reservation_hold',{...stay,guests:1}),/Idempotency key/);assert.equal((await call('reservation_get',{reservation_id:hold.reservation_id}))[0].guests,2);});
await test('room closure blocks new holds without breaking an existing retry',async()=>{await call('lodging_unit_upsert',{...input,active:false});assert.equal((await call('reservation_hold',stay))[0].reservation_id,hold.reservation_id);await fails(()=>call('reservation_hold',{...stay,idempotency_key:suffix+'-closed',arrival:'2030-06-01',departure:'2030-06-02'}),/Room inactive/);await call('lodging_unit_upsert',input);});
await test('adjacent dates do not overlap',async()=>{assert.equal((await call('lodging_availability',{...query,arrival:stay.departure,departure:'2030-05-05'})).length,1);});
await test('guest sees own booking; another provider cannot read or mutate it',async()=>{assert.equal((await call('reservation_get',{reservation_id:hold.reservation_id},'av_customer'))[0].reservation_id,hold.reservation_id);assert.equal((await call('reservation_get',{reservation_id:hold.reservation_id},'av_other')).length,0);assert.equal((await call('reservation_transition',{reservation_id:hold.reservation_id,status:'cancelled',expected_version:1},'av_other')).length,0);await fails(()=>call('reservation_transition',{reservation_id:hold.reservation_id,status:'confirmed',expected_version:1},'av_customer'),/Staff role/);});
await test('stale version and skipped state transitions fail',async()=>{await fails(()=>call('reservation_transition',{reservation_id:hold.reservation_id,status:'confirmed',expected_version:9}),/Stale version/);await fails(()=>call('reservation_transition',{reservation_id:hold.reservation_id,status:'checked_out',expected_version:1}),/invalid reservation transition/);});
await test('confirmation replay does not increment version or claim payment',async()=>{const request={reservation_id:hold.reservation_id,status:'confirmed',expected_version:1};const x=(await call('reservation_transition',request))[0];assert.equal(x.version,2);const y=(await call('reservation_transition',request))[0];assert.equal(y.version,2);assert.equal(y.modified_at,x.modified_at);});
await test('check-in and checkout advance the lifecycle',async()=>{assert.equal((await call('reservation_transition',{reservation_id:hold.reservation_id,status:'checked_in',expected_version:2}))[0].version,3);await fails(()=>call('reservation_transition',{reservation_id:hold.reservation_id,status:'cancelled',expected_version:3}),/invalid reservation transition/);assert.equal((await call('reservation_transition',{reservation_id:hold.reservation_id,status:'checked_out',expected_version:3}))[0].version,4);});
await test('terminal booking cannot be revived',async()=>{await fails(()=>call('reservation_transition',{reservation_id:hold.reservation_id,status:'confirmed',expected_version:4}),/invalid reservation transition/);assert.equal((await call('reservation_hold',stay))[0].status,'checked_out');});
const expiry=(await call('reservation_hold',{...stay,idempotency_key:suffix+'-expiry'}))[0];
sql(`UPDATE adiona.reservations SET expires_at=now()-interval '1 second' WHERE reservation_id=${expiry.reservation_id}`);
await test('expired hold cannot confirm and blocks until explicit release',async()=>{await fails(()=>call('reservation_transition',{reservation_id:expiry.reservation_id,status:'confirmed',expected_version:1}),/invalid reservation transition/);assert.equal((await call('lodging_availability',query)).length,0);assert.equal((await call('reservation_release_expired',{},'av_other')).length,0);const released=await call('reservation_release_expired');assert.ok(released.some(x=>x.reservation_id===expiry.reservation_id));assert.equal((await call('reservation_release_expired')).length,0);assert.equal((await call('lodging_availability',query)).length,1);});
await test('missing guest rolls back the reservation',async()=>{await fails(()=>call('reservation_hold',{...stay,idempotency_key:suffix+'-bad-guest',guest_id:'99999999'}),/foreign key/);assert.equal(sql(`SELECT count(*) FROM adiona.reservations WHERE idempotency_key='${suffix}-bad-guest'`),'0');});
await test('foreign room ownership and invalid currency are rejected',async()=>{await fails(()=>call('lodging_unit_upsert',{...input,provider_id:sql("SELECT user_id FROM adiona.principals WHERE db_role='av_other'"),unit_code:suffix+'-forged'},'av_admin'),/foreign key/);await fails(()=>call('lodging_unit_upsert',{...input,currency_code:'XXX'}),/foreign key/);});
await test('another room remains available for the same dates',async()=>{const second=(await call('lodging_unit_upsert',{...input,unit_code:'102-'+suffix}))[0];assert.notEqual(second.unit_id,unit.unit_id);assert.equal((await call('lodging_availability',query)).length,2);await call('lodging_unit_upsert',{...input,unit_code:'102-'+suffix,active:false});});
const cancelled=(await call('reservation_hold',{...stay,idempotency_key:suffix+'-cancel'}))[0];
await test('cancellation releases inventory and preserves history',async()=>{const x=(await call('reservation_transition',{reservation_id:cancelled.reservation_id,status:'cancelled',expected_version:1}))[0];assert.equal(x.status,'cancelled');assert.equal((await call('lodging_availability',query)).length,1);});
await test('database privileges prevent altering immutable snapshots',async()=>{assert.throws(()=>execFileSync(process.env.PSQL||'psql',['-X','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p','55439','-U','av_provider','-d','adiona_validation','-c',`UPDATE adiona.reservations SET nightly_rate=1 WHERE reservation_id=${hold.reservation_id}`],{stdio:'pipe'}),e=>/permission denied/.test(String(e.stderr)));});
// Concurrent direct calls use separate actual Rust-tool connections. Runtime calls use one
// deployment credential; serialization failures are reported, never silently retried by this runner.
await test('six competing holds cannot double-book',async()=>{const results=await Promise.allSettled(Array.from({length:6},(_,i)=>call('reservation_hold',{...stay,idempotency_key:suffix+'-race-'+i})));assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.equal(sql(`SELECT count(*) FROM adiona.reservations WHERE unit_id=${unit.unit_id} AND status='held'`),'1');});
if(!runtime)await test('six identical concurrent retries return one reservation',async()=>{const request={...stay,idempotency_key:suffix+'-same-race',arrival:'2030-08-01',departure:'2030-08-02'};const results=await Promise.all(Array.from({length:6},()=>call('reservation_hold',request)));assert.equal(new Set(results.map(r=>r[0].reservation_id)).size,1);});
await test('repeat migration preserves reservations and detects ledger drift',async()=>{const before=sql('SELECT count(*) FROM adiona.reservations');await call('lodging_provision',{},'migration_owner');assert.equal(sql('SELECT count(*) FROM adiona.reservations'),before);sql("UPDATE adiona_migrations.versions SET sha256='tampered' WHERE version=2");try{await fails(()=>call('lodging_provision',{},'migration_owner'),/checksum mismatch/);}finally{sql("UPDATE adiona_migrations.versions SET sha256='"+fs.readFileSync(path.join(root,'docs/migration-2-sha256.txt'),'utf8').trim()+"' WHERE version=2");}});
fs.writeFileSync(path.join(root,'docs',`hospitality-${suffix}-results.json`),JSON.stringify({postgres_version:sql('SHOW server_version'),checks:passed,executions},null,2)+'\n');
console.log(`PASS ${passed} hospitality checks (${suffix}); ${executions.length} runtime executions`);
