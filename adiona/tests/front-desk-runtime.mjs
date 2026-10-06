// Register scoped fixtures on the isolated runtime; no production endpoint is configurable.
import fs from 'node:fs';import path from 'node:path';import {execFileSync} from 'node:child_process';import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dir=execFileSync(process.env.PSQL||'psql',['-X','-At','-h','127.0.0.1','-p','55439','-U','migration_owner','-d','adiona_validation','-c','SHOW data_directory'],{encoding:'utf8'}).trim();
if(fs.realpathSync(dir)!==fs.realpathSync(path.join(root,'.local/pgdata-19')))throw Error('Wrong validation database');
const out=path.join(fs.mkdtempSync(path.join(root,'.local/scoped-')),'export');
execFileSync(process.execPath,[path.join(root,'scripts/export-front-desk.mjs'),'validation','adiona_provider_validation',out],{stdio:'inherit'});
async function post(route,data){const r=await fetch('http://127.0.0.1:58082'+route,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(data)});const text=await r.text();if(!r.ok)throw Error(`Local runtime HTTP ${r.status}`);return text;}
await post('/api/credentials',{name:'adiona_provider_validation',type:'postgres',data:{db_host:'127.0.0.1',db_port:55439,db_name:'adiona_validation',db_user:'av_provider',db_password:''}});
const bindings={};for(const [action,entry] of Object.entries(JSON.parse(fs.readFileSync(path.join(out,'manifest.json'),'utf8')))){
 const result=await post('/api/catalog/register',{content:fs.readFileSync(path.join(out,entry.file),'utf8')});
 // Extract the decimal token without parsing it as a JavaScript Number.
 const id=result.match(/"catalog_id"\s*:\s*(?:"(\d+)"|(\d+))/);if(!id)throw Error('Registration did not return a catalog ID');bindings[action]=id[1]||id[2];
}
fs.writeFileSync(path.join(root,'.local/scoped-live-bindings.json'),JSON.stringify({bindings:{'7':bindings}},null,2)+'\n');
console.log('Registered six provider-scoped catalog fixtures; run the gateway real_runtime_scoped_actions test.');

const fixture=execFileSync(process.env.PSQL||'psql',['-X','-At','-h','127.0.0.1','-p','55439','-U','migration_owner','-d','adiona_validation','-c',"SELECT json_build_object('unit_id',u.unit_id::text,'guest_id',(SELECT user_id::text FROM adiona.principals WHERE db_role='av_customer')) FROM adiona.lodging_units u WHERE u.provider_id=(SELECT user_id FROM adiona.principals WHERE db_role='av_provider') AND u.active ORDER BY u.unit_id LIMIT 1"],{encoding:'utf8'}).trim();
if(!fixture)throw Error('Run catalog and hospitality fixtures first');
fs.writeFileSync(path.join(root,'.local/scoped-live-request.json'),fixture+'\n');
