import assert from 'node:assert/strict';
import {execFileSync, spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const binary=path.join(root,'tests/rust/target/debug/adiona-noetl-validation');
let passed=0;
function call(name,request={},login='av_admin') {
 const raw=execFileSync(binary,[path.join(root,'playbooks',name+'.yaml'),login,JSON.stringify(request)],{encoding:'utf8',stdio:['ignore','pipe','pipe']});
 return (JSON.parse(raw).rows||[]).map(x=>x.result??x);
}
function sql(query,login='migration_owner') {
 return execFileSync(process.env.PSQL||'psql',['-X','-v','ON_ERROR_STOP=1','-At','-h','127.0.0.1','-p','55439','-U',login,'-d','adiona_validation','-c',query],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
}
function test(label,fn){fn();passed++;console.log('PASS '+label);}
function fails(fn,pattern){assert.throws(fn,e=>pattern.test(String(e.stderr||e)));}
test('PostgreSQL major 19 target',()=>{const version=Number(sql('SHOW server_version_num'));assert.ok(version>=190000&&version<200000,'PostgreSQL 19 server required');});
console.log('Database version: '+sql('SHOW server_version'));
call('reset',{},'migration_owner');
call('provision',{},'migration_owner');
sql(`DO $$ BEGIN
 FOR r IN 1..4 LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=CASE r WHEN 1 THEN 'av_admin' WHEN 2 THEN 'av_provider' WHEN 3 THEN 'av_other' ELSE 'av_customer' END) THEN
   EXECUTE format('CREATE ROLE %I LOGIN',CASE r WHEN 1 THEN 'av_admin' WHEN 2 THEN 'av_provider' WHEN 3 THEN 'av_other' ELSE 'av_customer' END);
  END IF;
 END LOOP;
END $$;
GRANT adiona_runtime TO av_admin,av_provider,av_other,av_customer;
ALTER ROLE av_admin IN DATABASE adiona_validation SET default_transaction_isolation='serializable';
ALTER ROLE av_provider IN DATABASE adiona_validation SET default_transaction_isolation='serializable';
ALTER ROLE av_other IN DATABASE adiona_validation SET default_transaction_isolation='serializable';
INSERT INTO adiona.principals(db_role,permission) VALUES('av_admin','admin');`);
test('repeat provisioning preserves migration ledger',()=>{call('provision',{},'migration_owner');assert.equal(sql('SELECT count(*) FROM adiona_migrations.versions'),'1');});
test('actual PostgreSQL source fixture can be provisioned twice',()=>{call('source_postgres_fixture',{},'migration_owner');call('source_postgres_fixture',{},'migration_owner');});
call('language_upsert',{lang_code:'en',lang_name:'English'});
call('language_upsert',{lang_code:'fr',lang_name:'French'});
call('currency_upsert',{currency_code:'usd',currency_name:'US Dollar',exchange_rate:1});
const types=call('user_type_list');
const providerType=types.find(x=>x.user_type_name==='SERVICE_PROVIDER').user_type_id;
const customerType=types.find(x=>x.user_type_name==='CUSTOMER').user_type_id;
const profile={user_type_id:providerType,email:'provider@example.invalid',display_name:'Synthetic Provider',first_name:'Synthetic',last_name:'Provider',currency:'usd'};
const provider=call('user_upsert',profile)[0];
const other=call('user_upsert',{...profile,email:'other@example.invalid'})[0];
const customer=call('user_upsert',{...profile,user_type_id:customerType,email:'customer@example.invalid'})[0];
sql(`INSERT INTO adiona.principals(db_role,user_id,permission) VALUES ('av_provider',${provider.user_id},'provider'),('av_other',${other.user_id},'provider'),('av_customer',${customer.user_id},'customer');`);
test('user upsert preserves identity and creation timestamp',()=>{let u=call('user_upsert',{...profile,display_name:'Updated'})[0];assert.equal(u.user_id,provider.user_id);assert.equal(u.created_dtm,provider.created_dtm);assert.equal(u.currency,'USD');});
test('user validation rejects malformed email',()=>fails(()=>call('user_upsert',{...profile,email:'invalid'}),/check constraint/));
test('customer cannot create users or elevate role',()=>{fails(()=>call('user_upsert',profile,'av_customer'),/not authorized/);fails(()=>sql(`UPDATE adiona.users SET user_type_id=1 WHERE user_id=${customer.user_id}`,'av_customer'),/Only profile/);});
test('self profile edits work without granting identity/role changes',()=>{const rows=call('user_profile_update',{display_name:'My profile',first_name:'A',last_name:'B'},'av_customer');assert.equal(rows[0].user_id,customer.user_id);assert.equal(call('user_get',{},'av_customer')[0].display_name,'My profile');});
test('cross-user PII is hidden by database RLS',()=>assert.equal(call('user_get',{user_id:provider.user_id},'av_customer').length,0));
const catType=call('category_type_upsert',{category_type:'tour_category'})[0];
const category=call('category_upsert',{category_name:'Walking tours',category_type_id:catType.category_type_id})[0];
call('category_translation_upsert',{category_id:category.category_id,lang_code:'en',category:'Walking tours'});
call('category_type_translation_upsert',{category_type_id:catType.category_type_id,lang_code:'fr',category_type:'Visites'});
call('category_image_upsert',{category_id:category.category_id,category_image_uri:'gs://synthetic/catalog/category.jpg',is_main_image:'Y'});
test('legacy category filter mapping and localized label',()=>{assert.equal(call('category_filter_list',{type:'tours',lang:'en'})[0].category_id,category.category_id);});
test('natural-key category retries return the same id',()=>assert.equal(call('category_upsert',{category_name:'Walking tours',category_type_id:catType.category_type_id})[0].category_id,category.category_id));
test('catalog taxonomy is admin-only',()=>fails(()=>call('category_upsert',{category_name:'Forbidden',category_type_id:catType.category_type_id},'av_provider'),/not authorized/));
const itemInput={provider_id:provider.user_id,item_name:'Generic product or service',price:1099,item_header:'Header',item_slug:'synthetic-service'};
const item=call('item_upsert',itemInput,'av_provider')[0];
test('item and default translation created atomically',()=>{const got=call('item_get',{item_id:item.item_id},'av_customer')[0];assert.equal(got.price,1099);assert.equal(got.content[0].item_header,'Header');});
test('repeat item upsert reuses id and updates price',()=>assert.equal(call('item_upsert',{...itemInput,price:1199},'av_provider')[0].item_id,item.item_id));
test('negative prices fail without changing persisted price',()=>{fails(()=>call('item_update',{item_id:item.item_id,price:-1},'av_provider'),/check constraint/);assert.equal(call('item_get',{item_id:item.item_id})[0].price,1199);});
test('cross-provider writes rejected by both playbook and RLS',()=>{fails(()=>call('item_upsert',itemInput,'av_other'),/not authorized/);assert.equal(call('item_update',{item_id:item.item_id,price:1},'av_other').length,0);assert.equal(sql(`WITH x AS (UPDATE adiona.items SET price=1 WHERE item_id=${item.item_id} RETURNING *) SELECT count(*) FROM x`,'av_other'),'0');});
test('customers cannot write catalog or spoof provider_id',()=>fails(()=>call('item_upsert',itemInput,'av_customer'),/not authorized/));
test('bound SQL safely preserves quotes and injection-like text',()=>{const text="O'Reilly'); DROP TABLE adiona.items; -- {{ secrets.password }}";call('item_translation_upsert',{item_id:item.item_id,lang_code:'fr',item_name:'Service',item_desc:text,item_slug:'service-fr'},'av_provider');assert.equal(call('item_get',{item_id:item.item_id})[0].content.find(x=>x.lang_code==='fr').item_desc,text);});
test('requested translation and default-language fallback',()=>{assert.equal(call('catalog_list',{lang:'fr'},'av_customer')[0].lang_code,'fr');assert.equal(call('catalog_list',{lang:'es'},'av_customer')[0].lang_code,'en');});
test('failure in second write rolls back first item write',()=>{fails(()=>call('item_upsert',{...itemInput,item_name:'Must rollback'},'av_provider'),/unique constraint/);assert.equal(sql("SELECT count(*) FROM adiona.items WHERE item_name='Must rollback'"),'0');});
test('foreign-key failure rolls back relationship insert',()=>fails(()=>call('item_category_link',{item_id:item.item_id,category_id:999999},'av_provider'),/foreign key/));
call('item_category_link',{item_id:item.item_id,category_id:category.category_id},'av_provider');
test('category relationship retries do not duplicate',()=>{call('item_category_link',{item_id:item.item_id,category_id:category.category_id},'av_provider');assert.equal(call('catalog_list',{category_id:category.category_id},'av_customer').length,1);});
call('item_image_upsert',{item_id:item.item_id,item_image_uri:'gs://synthetic/catalog/item.jpg',is_main_image:'Y'},'av_provider');
const attribute=call('attribute_upsert',{attribute_category_id:category.category_id,attribute_name:'max_adults'})[0];
const ia=call('item_attribute_upsert',{item_id:item.item_id,attribute_id:attribute.attribute_id,attribute_value:4},'av_provider')[0];
call('item_attribute_translation_upsert',{item_attribute_id:ia.item_attribute_id,lang_code:'en',attribute_content:'Four adults'},'av_provider');
test('attributes and media relationships are preserved',()=>{const x=call('item_get',{item_id:item.item_id})[0];assert.equal(x.attributes[0].attribute_value,4);assert.equal(x.images[0].item_image_uri,'gs://synthetic/catalog/item.jpg');});
test('other providers cannot change owned child rows',()=>fails(()=>call('item_attribute_translation_upsert',{item_attribute_id:ia.item_attribute_id,lang_code:'en',attribute_content:'No'},'av_other'),/not authorized/));
const bundle=call('item_upsert',{provider_id:provider.user_id,item_name:'Bundle',is_bundle:1,price:2000,item_slug:'synthetic-bundle'},'av_provider')[0];
call('bundle_link',{bundle_id:bundle.item_id,item_id:item.item_id},'av_provider');
test('bundle relationships replay and reject self-cycle',()=>{call('bundle_link',{bundle_id:bundle.item_id,item_id:item.item_id},'av_provider');assert.equal(call('item_get',{item_id:bundle.item_id})[0].bundle.length,1);fails(()=>call('bundle_link',{bundle_id:bundle.item_id,item_id:bundle.item_id},'av_admin'),/cycle|check constraint/);});
test('nested bundle cycles are rejected',()=>{
 const nested=call('item_upsert',{provider_id:provider.user_id,item_name:'Nested bundle',is_bundle:1,item_slug:'nested-bundle'},'av_provider')[0];
 call('bundle_link',{bundle_id:nested.item_id,item_id:bundle.item_id},'av_provider');
 fails(()=>call('bundle_link',{bundle_id:bundle.item_id,item_id:nested.item_id},'av_provider'),/Bundle cycle/);
});
test('category and category-type ancestry reject cycles',()=>{
 const child=call('category_upsert',{category_name:'Child',category_type_id:catType.category_type_id})[0];
 call('category_parent_set',{category_id:child.category_id,master_category_id:category.category_id});
 fails(()=>call('category_parent_set',{category_id:category.category_id,master_category_id:child.category_id}),/Hierarchy cycle/);
 const ct=call('category_type_upsert',{category_type:'child_type'})[0];
 call('category_type_parent_set',{category_type_id:ct.category_type_id,master_category_type_id:catType.category_type_id});
 fails(()=>call('category_type_parent_set',{category_type_id:catType.category_type_id,master_category_type_id:ct.category_type_id}),/Hierarchy cycle/);
});
test('graph mutation refuses a weaker isolation level',()=>{
 sql("ALTER ROLE av_provider IN DATABASE adiona_validation SET default_transaction_isolation='read committed'");
 try{fails(()=>call('bundle_link',{bundle_id:bundle.item_id,item_id:item.item_id},'av_provider'),/SERIALIZABLE/);}finally{sql("ALTER ROLE av_provider IN DATABASE adiona_validation SET default_transaction_isolation='serializable'");}
});
test('forged child ownership fails the composite foreign key',()=>{
 call('language_upsert',{lang_code:'de',lang_name:'German'});
 fails(()=>sql(`INSERT INTO adiona.item_content(item_id,provider_id,lang_code) VALUES (${item.item_id},${other.user_id},'de')`,'av_other'),/foreign key/);
});
test('unknown translation language rejects mutation',()=>fails(()=>call('item_translation_upsert',{item_id:item.item_id,lang_code:'zz',item_name:'Invalid language'},'av_provider'),/foreign key/));
test('identity upsert uses stable provider subject; no raw tokens',()=>{let x=call('user_identity_upsert',{user_id:customer.user_id,method:'oidc-example',id:'synthetic-subject'})[0];assert.equal(call('user_identity_upsert',{user_id:customer.user_id,method:'oidc-example',id:'synthetic-subject'})[0].user_auth_id,x.user_auth_id);assert.equal(call('user_identity_list',{},'av_customer')[0].id,'synthetic-subject');assert.equal(sql("SELECT count(*) FROM information_schema.columns WHERE table_schema='adiona' AND column_name IN ('access_token','refresh_token','api_token')"),'0');});
test('identity linking requires admin; subject cannot link to another user',()=>{fails(()=>call('user_identity_upsert',{user_id:customer.user_id,method:'oidc-example',id:'evil'},'av_customer'),/not authorized/);fails(()=>call('user_identity_upsert',{user_id:other.user_id,method:'oidc-example',id:'synthetic-subject'}),/unique constraint/);});
test('referenced parents cannot be deleted',()=>{fails(()=>call('item_delete',{item_id:item.item_id},'av_provider'),/foreign key/);fails(()=>call('user_delete',{user_id:provider.user_id}),/foreign key/);fails(()=>call('category_delete',{category_id:category.category_id}),/foreign key/);});
test('explicit unlink and deletion remove only selected item',()=>{
 call('bundle_unlink',{bundle_id:bundle.item_id,item_id:item.item_id},'av_provider');
 call('item_category_unlink',{item_id:item.item_id,category_id:category.category_id},'av_provider');
 call('item_image_delete',{item_id:item.item_id,item_image_uri:'gs://synthetic/catalog/item.jpg'},'av_provider');
 call('item_attribute_translation_delete',{item_attribute_id:ia.item_attribute_id,lang_code:'en'},'av_provider');
 call('item_attribute_delete',{item_id:item.item_id,attribute_id:attribute.attribute_id},'av_provider');
 for(const lang_code of ['en','fr'])call('item_translation_delete',{item_id:item.item_id,lang_code},'av_provider');
 assert.equal(call('item_delete',{item_id:item.item_id},'av_provider')[0].item_id,item.item_id);
 assert.equal(call('item_get',{item_id:item.item_id}).length,0);
 assert.equal(call('item_get',{item_id:bundle.item_id}).length,1);
});
test('repeat provisioning never resets business data',()=>{call('provision',{},'migration_owner');assert.equal(call('item_get',{item_id:bundle.item_id}).length,1);});
test('unmapped runtime identity cannot see rows or provision',()=>{sql("DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='av_unmapped') THEN CREATE ROLE av_unmapped LOGIN; END IF; END $$; GRANT adiona_runtime TO av_unmapped;");assert.equal(call('catalog_list',{},'av_unmapped').length,0);fails(()=>call('provision',{},'av_unmapped'),/permission denied/);});
test('checksum drift fails without losing data',()=>{sql("UPDATE adiona_migrations.versions SET sha256='tampered' WHERE version=1");fails(()=>call('provision',{},'migration_owner'),/checksum mismatch/);sql("UPDATE adiona_migrations.versions SET sha256='"+execFileSync('cat',[path.join(root,'docs/migration-sha256.txt')],{encoding:'utf8'}).trim()+"' WHERE version=1");});
// True concurrent connections execute the same natural-key mutation.
const concurrent={provider_id:provider.user_id,item_name:'Concurrent retry',price:500,item_slug:'concurrent'};
async function concurrentCall(attempt=0){try{return await new Promise((resolve,reject)=>{
 const child=spawn(binary,[path.join(root,'playbooks/item_upsert.yaml'),'av_provider',JSON.stringify(concurrent)]);
 let out='',err='';child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);child.on('error',reject);child.on('close',(code,signal)=>code!==0?reject(Error(err||`Validation process exited with code ${code}, signal ${signal}`)):resolve(JSON.parse(out).rows[0].result.item_id));
});}catch(e){if(attempt<8&&/40001|40P01/.test(e.message)){await new Promise(resolve=>setTimeout(resolve,Math.min(250,10*2**attempt)+Math.random()*20));return concurrentCall(attempt+1);}throw e;}}
const outputs=await Promise.all(Array.from({length:6},()=>concurrentCall()));
test('six concurrent retries create one item and translation',()=>{assert.equal(new Set(outputs).size,1);assert.equal(sql("SELECT count(*) FROM adiona.items WHERE item_name='Concurrent retry'"),'1');});
console.log(`PASS ${passed} integration checks; upstream Rust PostgresTool + PostgreSQL; distributed orchestration not asserted.`);
