// Operator-only deterministic export. No network access, secret values or database access.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
export const actions = {availability:'lodging_availability',hold:'reservation_hold',reservation:'reservation_get',reservations:'reservation_list',transition:'reservation_transition',release_expired:'reservation_release_expired'};
export function scopedPlaybook(source,scope,credential,name){
 if(!/^[a-z][a-z0-9_-]{0,63}$/.test(scope)||!/^adiona_provider_[a-z0-9_]{1,64}$/.test(credential))throw Error('Use a stable scope and an adiona_provider_* credential alias');
 if((source.match(/auth: adiona_actor/g)||[]).length!==1||!source.includes(`path: adiona/v1/${name}\n`))throw Error('Unexpected source playbook');
 return source.replace(`name: adiona_${name}`,`name: adiona_${scope}_${name}`).replace(`path: adiona/v1/${name}`,`path: adiona/scoped/${scope}/${name}`).replace('auth: adiona_actor',`auth: ${credential}`);
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 const [scope,credential,out]=process.argv.slice(2);if(!out)throw Error('Usage: node export-front-desk.mjs SCOPE adiona_provider_ALIAS OUTPUT_DIRECTORY');
 const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');const entries={};
 // Validate every file before creating the output directory.
 for(const [action,name] of Object.entries(actions)){const content=scopedPlaybook(fs.readFileSync(path.join(root,'playbooks',name+'.yaml'),'utf8'),scope,credential,name);entries[action]={file:name+'.yaml',sha256:createHash('sha256').update(content).digest('hex'),content};}
 fs.mkdirSync(out,{recursive:false});
 for(const entry of Object.values(entries))fs.writeFileSync(path.join(out,entry.file),entry.content);
 fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify(Object.fromEntries(Object.entries(entries).map(([action,{content,...rest}])=>[action,rest])),null,2)+'\n');
 console.log(`Exported ${Object.keys(entries).length} scoped playbooks. Register with an operator credential, then bind their catalog IDs in the gateway.`);
}
