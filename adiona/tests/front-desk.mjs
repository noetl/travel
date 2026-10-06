import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {scopedPlaybook} from '../scripts/export-front-desk.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const binary=path.join(root,'tests/rust/target/debug/adiona-noetl-validation');
function sql(q){return execFileSync(process.env.PSQL||'psql',['-X','-At','-h','127.0.0.1','-p','55439','-U','migration_owner','-d','adiona_validation','-c',q],{encoding:'utf8'}).trim();}
assert.equal(fs.realpathSync(sql('SHOW data_directory')),fs.realpathSync(path.join(root,'.local/pgdata-19')));
function call(request,login='av_provider'){return JSON.parse(execFileSync(binary,[path.join(root,'playbooks/reservation_list.yaml'),login,JSON.stringify(request)],{encoding:'utf8',stdio:['ignore','pipe','pipe']})).rows.map(x=>x.result);}
let checks=0;function test(name,fn){fn();console.log('PASS '+name);checks++;}
const provider=sql("SELECT user_id FROM adiona.principals WHERE db_role='av_provider'");
test('staff list uses the database principal and decimal-string IDs',()=>{const rows=call({provider_id:'9999'});assert.ok(rows.length>0);assert.ok(rows.every(r=>r.provider_id===provider&&typeof r.reservation_id==='string'));});
test('another provider cannot list these bookings',()=>assert.equal(call({},'av_other').length,0));
test('customer cannot enumerate staff reservations',()=>assert.throws(()=>call({},'av_customer'),e=>/Staff role required/.test(String(e.stderr))));
test('list supports status, arrival and keyset filters',()=>{const rows=call({status:'held',arrival:'2030-05-01'});assert.ok(rows.length>0);assert.ok(rows.every(r=>r.status==='held'&&r.arrival==='2030-05-01'));const next=call({before_id:rows[0].reservation_id});assert.ok(next.every(r=>BigInt(r.reservation_id)<BigInt(rows[0].reservation_id)));});
test('bound invalid dates fail instead of becoming SQL',()=>assert.throws(()=>call({arrival:"';DROP TABLE adiona.reservations;--"})));
const source=fs.readFileSync(path.join(root,'playbooks/reservation_list.yaml'),'utf8');
test('scope export changes only identity metadata and a fixed credential alias',()=>{const scoped=scopedPlaybook(source,'hotel_one','adiona_provider_one','reservation_list');assert.equal(scoped.split('      command: |')[1],source.split('      command: |')[1]);assert.match(scoped,/auth: adiona_provider_one/);assert.match(scoped,/path: adiona\/scoped\/hotel_one\/reservation_list/);});
test('scope export refuses privileged and malformed aliases',()=>{for(const alias of ['adiona_migrator','{{ request.credential }}','admin\nauth: anything'])assert.throws(()=>scopedPlaybook(source,'hotel_one',alias,'reservation_list'));});
fs.writeFileSync(path.join(root,'docs/front-desk-database-results.json'),JSON.stringify({postgres_version:sql('SHOW server_version'),checks},null,2)+'\n');console.log(`PASS ${checks} front-desk database/export checks`);
