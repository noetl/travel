import concurrent.futures, threading, unittest
from pathlib import Path
from local.adapter import Adapter, DomainError, make_server
from local.check_playbooks import run, validate
ROOT=Path(__file__).resolve().parents[1]
class BookingTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.;self.a=Adapter(clock=lambda:self.now);self.n=0
    def call(self,endpoint,body,role='staff',key=None):
        self.n+=1
        return self.a.command(endpoint,'demo-'+role,key or str(self.n),{'property_id':'ranch-demo',**body})
    def quote(self,room='room-1',arrival='2027-10-02',departure='2027-10-04'):
        return self.call('quotes',{'room_id':room,'arrival':arrival,'departure':departure,'guests':2})
    def hold(self,**kw):return self.call('holds',{'quote_id':self.quote(**kw)['quote_id']})
    def payment(self,r,outcome='captured'):return self.call('test/payments',{'reservation_id':r['reservation_id'],'outcome':outcome},'worker')
    def confirm(self,r,p,key=None):return self.call('confirmations',{'reservation_id':r['reservation_id'],'payment_id':p['payment_id']},'worker',key)
    def error(self,code,fn):
        with self.assertRaises(DomainError) as raised:fn()
        self.assertEqual(raised.exception.code,code)
    def test_happy_path_and_duplicate_confirmation(self):
        r=self.hold();p=self.payment(r);a=self.confirm(r,p,'same');b=self.confirm(r,p,'same');c=self.confirm(r,p,'new')
        self.assertEqual(a,b);self.assertEqual(b,c);self.assertEqual(a['state'],'confirmed')
        self.assertEqual(sum(e['type']=='reservation.confirmed' for e in self.a.outbox),1)
    def test_last_room_concurrent_holds(self):
        quotes=[self.quote() for _ in range(12)]
        def attempt(pair):
            i,q=pair
            try:return self.a.command('holds','demo-staff',str(i),{'property_id':'ranch-demo','quote_id':q['quote_id']})['state']
            except DomainError as e:return e.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:states=list(pool.map(attempt,enumerate(quotes)))
        self.assertEqual(states.count('held'),1);self.assertEqual(states.count('inventory_unavailable'),11)
    def test_request_payload_conflict(self):
        q=self.quote();self.call('holds',{'quote_id':q['quote_id']},key='key')
        self.error('idempotency_conflict',lambda:self.call('holds',{'quote_id':self.quote('room-2')['quote_id']},key='key'))
    def test_same_quote_different_keys_one_hold(self):
        q=self.quote();a=self.call('holds',{'quote_id':q['quote_id']});b=self.call('holds',{'quote_id':q['quote_id']})
        self.assertEqual(a,b);self.assertEqual(len(self.a.reservations),1)
    def test_adjacent_stays_do_not_overlap(self):
        self.hold();self.assertEqual(self.hold(arrival='2027-10-04',departure='2027-10-05')['state'],'held')
    def test_expired_quote(self):
        q=self.quote();self.now+=301
        self.error('quote_expired',lambda:self.call('holds',{'quote_id':q['quote_id']}))
    def test_expire_releases_inventory(self):
        self.hold();self.now+=601
        self.assertEqual(self.call('holds/expire',{'limit':100},'worker')['count'],1)
        self.assertEqual(self.hold()['state'],'held')
    def test_hold_reclaims_expired_without_sweeper(self):
        old=self.hold();self.now+=601;new=self.hold();self.assertNotEqual(old['reservation_id'],new['reservation_id'])
    def test_late_payment_preserves_new_inventory_owner(self):
        old=self.hold();self.now+=601;new=self.hold();p=self.payment(old)
        self.assertEqual(self.confirm(old,p)['state'],'needs_refund')
        self.assertTrue(all(v==new['reservation_id'] for v in self.a.inventory.values()))
    def test_capture_then_expire_goes_to_refund_review(self):
        r=self.hold();self.payment(r);self.now+=601;self.call('holds/expire',{'limit':100},'worker')
        self.assertEqual(self.a.reservations[r['reservation_id']]['state'],'needs_refund')
    def test_reclaim_captured_expired_hold_preserves_refund_requirement(self):
        old=self.hold();self.payment(old);self.now+=601;self.hold()
        self.assertEqual(self.a.reservations[old['reservation_id']]['state'],'needs_refund')
        self.assertEqual(sum(e['type']=='reservation.needs_refund' for e in self.a.outbox),1)
    def test_decline_does_not_confirm(self):
        r=self.hold();p=self.payment(r,'declined');self.error('payment_not_captured',lambda:self.confirm(r,p))
    def test_unpaid_cancel_releases_inventory(self):
        r=self.hold();self.call('holds/cancel',{'reservation_id':r['reservation_id']});self.assertEqual(self.hold()['state'],'held')
    def test_paid_hold_cannot_use_unpaid_cancel(self):
        r=self.hold();self.payment(r)
        self.error('captured_payment_requires_refund_flow',lambda:self.call('holds/cancel',{'reservation_id':r['reservation_id']}))
    def test_cross_tenant_id_not_found(self):
        q=self.quote();self.error('not_found',lambda:self.a.command('holds','other-staff','x',{'property_id':'other-demo','quote_id':q['quote_id']}))
    def test_staff_cannot_forge_payment(self):
        r=self.hold();self.error('forbidden',lambda:self.call('test/payments',{'reservation_id':r['reservation_id'],'outcome':'captured'}))
    def test_rejects_client_tenant_and_amount(self):
        self.error('invalid_fields',lambda:self.call('quotes',{'room_id':'room-1','arrival':'2027-10-02','departure':'2027-10-04','guests':2,'tenant_id':'tenant-a','amount_minor':1}))
    def test_payment_must_belong_to_reservation(self):
        a=self.hold();b=self.hold(room='room-2');p=self.payment(b);self.error('payment_reservation_mismatch',lambda:self.confirm(a,p))
    def test_payment_amount_checked(self):
        r=self.hold();p=self.payment(r);self.a.payments[p['payment_id']]['amount_minor']=1
        self.error('payment_amount_mismatch',lambda:self.confirm(r,p))
    def test_mock_payment_is_unique_per_reservation(self):
        r=self.hold();a=self.payment(r);b=self.payment(r);self.assertEqual(a,b);self.assertEqual(len(self.a.payments),1)
    def test_bounded_expiration(self):
        self.hold();self.hold(room='room-2');self.now+=601;self.assertEqual(self.call('holds/expire',{'limit':1},'worker')['count'],1)
    def test_date_and_occupancy_validation(self):
        self.error('invalid_stay_length',lambda:self.quote(departure='2027-10-02'))
        self.error('occupancy_exceeded',lambda:self.call('quotes',{'room_id':'room-1','arrival':'2027-10-02','departure':'2027-10-04','guests':True}))
    def test_all_playbooks_structurally_valid(self):
        files=list((ROOT/'playbooks').glob('*.yaml'));self.assertEqual(len(files),7)
        for f in files:validate(f)
    def test_demo_yaml_http_contract_and_replay(self):
        server=make_server(0,self.a);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            args={'api_base':f'http://127.0.0.1:{server.server_port}'}
            first=run(ROOT/'playbooks'/'booking_demo.yaml',args);second=run(ROOT/'playbooks'/'booking_demo.yaml',args)
            self.assertEqual(first,second);self.assertEqual(first['state'],'confirmed')
            self.assertEqual(len(self.a.reservations),1);self.assertEqual(len(self.a.payments),1)
        finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
