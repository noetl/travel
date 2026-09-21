"""Loopback-only, in-memory command adapter. Not a production database/service."""
from copy import deepcopy
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import threading
import time
import uuid

class DomainError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)

class Adapter:
    def __init__(self, clock=time.time):
        self.clock, self.lock = clock, threading.RLock()
        self.quotes, self.reservations, self.payments = {}, {}, {}
        self.inventory, self.requests, self.outbox = {}, {}, []
        self.principals = {
            'demo-staff': ('tenant-a', 'staff', 'ranch-demo'),
            'demo-worker': ('tenant-a', 'worker', 'ranch-demo'),
            'other-staff': ('tenant-b', 'staff', 'other-demo'),
            'other-worker': ('tenant-b', 'worker', 'other-demo'),
        }
        self.allowed = {
            'quotes': ('staff',), 'holds': ('staff',),
            'test/payments': ('worker',), 'confirmations': ('worker',),
            'holds/expire': ('worker',), 'holds/cancel': ('staff',),
        }
        self.fields = {
            'quotes': {'room_id', 'arrival', 'departure', 'guests'},
            'holds': {'quote_id'}, 'test/payments': {'reservation_id', 'outcome'},
            'confirmations': {'reservation_id', 'payment_id'},
            'holds/expire': {'limit'}, 'holds/cancel': {'reservation_id'},
        }

    def fail(self, code, status=409):
        raise DomainError(status, code)

    def ident(self, prefix):
        return prefix+'_'+uuid.uuid4().hex

    def event(self, reservation, event_type):
        # Real outbox rows must commit in the same PostgreSQL transaction.
        if any(e['reservation_id']==reservation['reservation_id'] and e['type']==event_type for e in self.outbox):
            return
        self.outbox.append({'event_id':self.ident('evt'),'tenant_id':reservation['tenant_id'],
            'property_id':reservation['property_id'],'reservation_id':reservation['reservation_id'],
            'type':event_type,'created_at':self.clock(),'delivery_status':'pending'})

    def owned(self, collection, ident, tenant, prop):
        obj=collection.get(ident)
        if not obj or (obj['tenant_id'],obj['property_id'])!=(tenant,prop):
            self.fail('not_found',404)
        return obj

    def release(self, reservation, new_state):
        for night in reservation['nights']:
            key=(reservation['tenant_id'],reservation['property_id'],reservation['room_id'],night)
            if self.inventory.get(key)==reservation['reservation_id']:
                del self.inventory[key]
        reservation['state']=new_state
        self.event(reservation,'reservation.'+new_state)

    def public_reservation(self, reservation):
        return {k:reservation[k] for k in ('reservation_id','state','expires_at','amount_minor','currency')}

    def command(self, endpoint, principal, key, payload):
        with self.lock:
            if principal not in self.principals: self.fail('unauthorized',401)
            tenant,role,prop=self.principals[principal]
            if endpoint not in self.allowed: self.fail('not_found',404)
            if role not in self.allowed[endpoint]: self.fail('forbidden',403)
            if not isinstance(payload,dict): self.fail('invalid_payload',422)
            if payload.get('property_id')!=prop: self.fail('forbidden',403)
            if set(payload)!=self.fields[endpoint]|{'property_id'}: self.fail('invalid_fields',422)
            if not isinstance(key,str) or not 1<=len(key)<=160 or key.startswith('REPLACE_'):
                self.fail('invalid_idempotency_key',422)
            if any(not isinstance(payload[f],str) or not payload[f] or len(payload[f])>160
                   for f in self.fields[endpoint]-{'guests','limit'}):
                self.fail('invalid_field_type',422)
            canonical=json.dumps(payload,sort_keys=True,separators=(',',':'))
            scope=(tenant,principal,endpoint,key)
            previous=self.requests.get(scope)
            if previous:
                if previous[0]!=canonical: self.fail('idempotency_conflict')
                return deepcopy(previous[1])
            result=getattr(self,'do_'+endpoint.replace('/','_'))(tenant,prop,payload)
            self.requests[scope]=(canonical,deepcopy(result))
            return deepcopy(result)

    def do_quotes(self,tenant,prop,p):
        try:
            arrival,departure=date.fromisoformat(p['arrival']),date.fromisoformat(p['departure'])
        except (ValueError,TypeError): self.fail('invalid_dates',422)
        count=(departure-arrival).days
        if not 1<=count<=30: self.fail('invalid_stay_length',422)
        if type(p['guests']) is not int or not 1<=p['guests']<=2: self.fail('occupancy_exceeded',422)
        if p['room_id'] not in ('room-1','room-2'): self.fail('room_not_found',404)
        # Fictional fixture: flat $100/night plus 10% tax. Not ranch pricing.
        q={'quote_id':self.ident('quo'),'tenant_id':tenant,'property_id':prop,
           'room_id':p['room_id'],'arrival':p['arrival'],'departure':p['departure'],
           'guests':p['guests'],'nights':[(arrival+timedelta(days=i)).isoformat() for i in range(count)],
           'subtotal_minor':count*10000,'tax_minor':count*1000,'amount_minor':count*11000,
           'currency':'USD','policy_version':'fictional-fixture-v1','expires_at':self.clock()+300}
        self.quotes[q['quote_id']]=q
        return deepcopy(q)

    def do_holds(self,tenant,prop,p):
        q=self.owned(self.quotes,p['quote_id'],tenant,prop)
        existing=next((r for r in self.reservations.values() if r['quote_id']==q['quote_id']),None)
        if existing: return self.public_reservation(existing)
        if q['expires_at']<=self.clock(): self.fail('quote_expired')
        keys=[(tenant,prop,q['room_id'],night) for night in q['nights']]
        stale=[]
        for k in keys:
            owner=self.inventory.get(k)
            if owner:
                r=self.reservations[owner]
                if r['state']=='held' and r['expires_at']<=self.clock(): stale.append(r)
                else: self.fail('inventory_unavailable')
        for r in stale:
            captured=any(v['reservation_id']==r['reservation_id'] and v['status']=='captured' for v in self.payments.values())
            self.release(r,'needs_refund' if captured else 'expired')
        r={**deepcopy(q),'reservation_id':self.ident('res'),'state':'held','expires_at':self.clock()+600}
        self.reservations[r['reservation_id']]=r
        for k in keys: self.inventory[k]=r['reservation_id']
        self.event(r,'reservation.held')
        return self.public_reservation(r)

    def do_test_payments(self,tenant,prop,p):
        r=self.owned(self.reservations,p['reservation_id'],tenant,prop)
        if p['outcome'] not in ('captured','declined'): self.fail('invalid_payment_outcome',422)
        existing=next((v for v in self.payments.values() if v['reservation_id']==r['reservation_id']),None)
        if existing:
            if existing['status']!=p['outcome']: self.fail('payment_outcome_conflict')
            return deepcopy(existing)
        payment={'payment_id':self.ident('pay'),'tenant_id':tenant,'property_id':prop,
            'reservation_id':r['reservation_id'],'status':p['outcome'],'provider':'simulator',
            'amount_minor':r['amount_minor'],'currency':r['currency']}
        self.payments[payment['payment_id']]=payment
        self.event(r,'payment.'+p['outcome'])
        return deepcopy(payment)

    def do_confirmations(self,tenant,prop,p):
        r=self.owned(self.reservations,p['reservation_id'],tenant,prop)
        payment=self.owned(self.payments,p['payment_id'],tenant,prop)
        if payment['reservation_id']!=r['reservation_id']: self.fail('payment_reservation_mismatch')
        if payment['status']!='captured': self.fail('payment_not_captured')
        if (payment['amount_minor'],payment['currency'])!=(r['amount_minor'],r['currency']):
            self.fail('payment_amount_mismatch')
        if r['state'] in ('confirmed','needs_refund'): return self.public_reservation(r)
        keys=[(tenant,prop,r['room_id'],night) for night in r['nights']]
        if r['state']!='held' or r['expires_at']<=self.clock() or any(self.inventory.get(k)!=r['reservation_id'] for k in keys):
            self.release(r,'needs_refund')
            return self.public_reservation(r)
        r['state']='confirmed'
        self.event(r,'reservation.confirmed')
        return self.public_reservation(r)

    def do_holds_expire(self,tenant,prop,p):
        if type(p['limit']) is not int or not 1<=p['limit']<=500: self.fail('invalid_limit',422)
        expired=[]
        for r in list(self.reservations.values()):
            if (r['tenant_id'],r['property_id'])==(tenant,prop) and r['state']=='held' and r['expires_at']<=self.clock():
                captured=any(v['reservation_id']==r['reservation_id'] and v['status']=='captured' for v in self.payments.values())
                self.release(r,'needs_refund' if captured else 'expired')
                expired.append(r['reservation_id'])
                if len(expired)>=p['limit']: break
        return {'expired_reservation_ids':expired,'count':len(expired)}

    def do_holds_cancel(self,tenant,prop,p):
        r=self.owned(self.reservations,p['reservation_id'],tenant,prop)
        if r['state'] in ('canceled','expired'): return self.public_reservation(r)
        if r['state']!='held': self.fail('cannot_cancel_unpaid_hold')
        if any(v['reservation_id']==r['reservation_id'] and v['status']=='captured' for v in self.payments.values()):
            self.fail('captured_payment_requires_refund_flow')
        self.release(r,'canceled')
        return self.public_reservation(r)

def make_server(port=8099, adapter=None):
    adapter=adapter or Adapter()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384: raise DomainError(413,'invalid_body_size')
                if not self.path.startswith('/v1/'): raise DomainError(404,'not_found')
                payload=json.loads(self.rfile.read(length))
                result=adapter.command(self.path[4:],self.headers.get('X-Demo-Principal'),self.headers.get('Idempotency-Key'),payload)
                status=200
            except DomainError as e: status,result=e.status,{'error':e.code}
            except (ValueError,TypeError): status,result=422,{'error':'invalid_json'}
            data=json.dumps(result).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8099)
    args=parser.parse_args()
    print(f'DEVELOPMENT ONLY: in-memory adapter at http://127.0.0.1:{args.port}',flush=True)
    make_server(args.port).serve_forever()
