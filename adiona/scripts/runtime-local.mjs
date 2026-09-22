// Starts/stops ONLY an isolated loopback validation runtime. No deployment.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn,execFileSync} from 'node:child_process';
import {randomBytes} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const local=path.join(root,'.local');fs.mkdirSync(local,{recursive:true});
if(process.argv[2]==='stop'){
 for(const name of ['worker','server']){
  const f=path.join(local,name+'.pid');if(!fs.existsSync(f))continue;
  const pid=Number(fs.readFileSync(f,'utf8'));
  try{
   const command=execFileSync('ps',['-p',String(pid),'-o','command='],{encoding:'utf8'}).trim();
   if(!command.includes('noetl-worker')&&!command.includes('noetl-control-plane'))throw Error('PID no longer belongs to the validation runtime');
   process.kill(pid,'SIGTERM');fs.unlinkSync(f);
  }catch(e){if(e.code!=='ESRCH')throw e;}
 }
 process.exit(0);
}
const source=process.env.NOETL_SOURCE_ROOT;
const target=process.env.NOETL_RUNTIME_TARGET;
if(!source||!target)throw Error('Set NOETL_SOURCE_ROOT (contains server and worker checkouts) and NOETL_RUNTIME_TARGET (Cargo target directory)');
try{const r=await fetch('http://127.0.0.1:58082/health',{signal:AbortSignal.timeout(500)});if(r)throw Error('port 58082 occupied');}catch(e){if(e.message==='port 58082 occupied')throw e;}
const args=['-X','-v','ON_ERROR_STOP=1','-h','127.0.0.1','-p','55439','-U','migration_owner','-d','adiona_validation'];
const actual=execFileSync(process.env.PSQL||'psql',[...args,'-At','-c','SHOW data_directory'],{encoding:'utf8'}).trim();
if(fs.realpathSync(actual)!==fs.realpathSync(path.join(local,'pgdata-19')))throw Error('PostgreSQL is not the cluster created by start-postgres.sh');
const version=Number(execFileSync(process.env.PSQL||'psql',[...args,'-At','-c','SHOW server_version_num'],{encoding:'utf8'}).trim());
if(version<190000||version>=200000)throw Error('PostgreSQL 19 server required');
execFileSync(process.env.PSQL||'psql',[...args,'-c','CREATE SCHEMA IF NOT EXISTS noetl'],{stdio:'ignore'});
execFileSync(process.env.PSQL||'psql',[...args,'-f',path.join(source,'server/db/ddl/postgres/schema_ddl.sql')],{stdio:'ignore'});
const keyFile=path.join(local,'runtime.key');if(!fs.existsSync(keyFile))fs.writeFileSync(keyFile,randomBytes(32).toString('base64'),{mode:0o600});
const common={PATH:process.env.PATH,RUST_LOG:'info',NOETL_INTERNAL_AUTH_MODE:'disabled',NOETL_COMMAND_BUS:'ehdb',NOETL_EVENT_BUS:'ehdb'};
for(const [name,bin,env] of [
 ['server','noetl-control-plane',{POSTGRES_HOST:'127.0.0.1',POSTGRES_PORT:'55439',POSTGRES_USER:'migration_owner',POSTGRES_DATABASE:'adiona_validation',NOETL_HOST:'127.0.0.1',NOETL_PORT:'58082',NOETL_PUBLIC_SERVER_URL:'http://127.0.0.1:58082',NOETL_ENCRYPTION_KEY:fs.readFileSync(keyFile,'utf8').trim(),NOETL_ORCHESTRATE_PLUGIN_DRIVE:'false',NOETL_STATE_BUILDER:'server',NOETL_COMMAND_BUS_WRITER_ADDRS:'0@127.0.0.1:59100',NOETL_EVENT_BUS_WRITER_ADDRS:'0@127.0.0.1:59103',NOETL_ENABLE_GCP_TOKEN_API:'false'}],
 ['worker','noetl-worker',{NOETL_SERVER_URL:'http://127.0.0.1:58082',WORKER_ID:'adiona-validation',WORKER_POOL_NAME:'shared',NOETL_FEED_FILTER_SUBJECT:'noetl.commands.shared.>',WORKER_METRICS_BIND:'127.0.0.1:59090',NOETL_COMMAND_BUS_HOST:'true',NOETL_COMMAND_BUS_WRITER_DIR:path.join(local,'command-bus-19'),NOETL_COMMAND_BUS_INGEST_BIND:'127.0.0.1:59100',NOETL_COMMAND_BUS_CLAIM_BIND:'127.0.0.1:59101',NOETL_COMMAND_BUS_CLAIM_ADDR:'127.0.0.1:59101',NOETL_EVENT_BUS_HOST:'true',NOETL_EVENT_BUS_WRITER_DIR:path.join(local,'event-bus-19'),NOETL_EVENT_BUS_INGEST_BIND:'127.0.0.1:59103'}]
]){
 const log=fs.openSync(path.join(local,name+'.log'),'a');
 const child=spawn(path.join(target,'debug',bin),[],{cwd:local,env:{...common,...env},detached:true,stdio:['ignore',log,log]});
 await new Promise((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject);});
 fs.writeFileSync(path.join(local,name+'.pid'),String(child.pid));child.unref();
 let healthy=false;
 for(let i=0;i<80;i++){
  try{const r=await fetch(name==='server'?'http://127.0.0.1:58082/health':'http://127.0.0.1:59090/healthz',{signal:AbortSignal.timeout(500)});if(r.ok){healthy=true;break;}}catch{}
  await new Promise(r=>setTimeout(r,250));
 }
 if(!healthy)throw Error(`${name} failed to become healthy; inspect .local/${name}.log and run runtime-local.mjs stop`);
 console.log('Ready: local Rust '+name);
}
