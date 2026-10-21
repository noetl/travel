#!/usr/bin/env python3
"""noetl/travel#166: hotel content comes from our own copy, never a live per-search
Content API call. Runs the playbooks' own embedded code offline, with every HTTP call
(GCP metadata, Secret Manager, HotelBeds, Firestore) stubbed and recorded.

  * playbooks/hotelbeds-content-sync.yaml: the record it keeps, the bounded and
    resumable full load, the daily delta, quota and Firestore failures, batching.
  * playbooks/itinerary-planner.yaml call_hotelbeds_hotels / call_hotelbeds_book: a
    search reads photos (and the address) from the copy in one Firestore batchGet
    and makes NO Content API request; a missing hotel or a Firestore failure leaves
    the hotel without photos, not the search broken; "live" still works as a rollback.
"""
import base64
import io
import json
import sys
import urllib.error
import urllib.request

import yaml

failures = []


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


# ── HTTP stub ────────────────────────────────────────────────────────────

class Resp(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(json.dumps(body).encode())
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


calls = []
routes = {}


def fake_urlopen(req, timeout=None):
    url = req.full_url
    body = json.loads(req.data.decode()) if getattr(req, "data", None) else None
    calls.append((req.get_method(), url, body))
    for key, handler in routes.items():
        if key in url:
            out = handler(url, body)
            if isinstance(out, tuple):
                status, payload = out
                if status >= 400:
                    raise urllib.error.HTTPError(url, status, "err", {}, io.BytesIO(json.dumps(payload).encode()))
                return Resp(payload, status)
            return Resp(out)
    raise AssertionError("unexpected URL " + url)


urllib.request.urlopen = fake_urlopen
SECRET = {"payload": {"data": base64.b64encode(json.dumps({"apikey": "k", "secret": "s"}).encode()).decode()}}


def base_routes():
    routes.clear()
    calls.clear()
    routes["metadata.google.internal"] = lambda u, b: {"access_token": "t"}
    routes["secretmanager.googleapis.com"] = lambda u, b: SECRET


# ── The sync playbook ────────────────────────────────────────────────────

sync_steps = {s["step"]: s for s in yaml.safe_load(open("playbooks/hotelbeds-content-sync.yaml"))["workflow"]}
lib = {"_SYNC_LIBRARY_ONLY": True}
exec(sync_steps["sync"]["tool"]["code"], lib)
content_record, run_sync, save_hotels = lib["content_record"], lib["run_sync"], lib["save_hotels"]

HB_HOTEL = {
    "code": 12345, "name": {"content": "Hotel Example"}, "city": {"content": "PARIS"},
    "address": {"content": "12 Rue Exemple"}, "postalCode": "75004", "countryCode": "FR",
    "destinationCode": "PAR", "zoneCode": 7, "coordinates": {"latitude": 48.859, "longitude": 2.362},
    "email": "info@example.com", "web": "www.example.com",
    "phones": [{"phoneNumber": "+33 1 00", "phoneType": "PHONEBOOKING"}, {"phoneNumber": ""}],
    "description": {"content": "x" * 5000},
    "images": [{"path": "00/012345/b.jpg", "order": 2, "imageTypeCode": "HAB", "roomCode": "DBL.ST"},
               {"path": "00/012345/a.jpg", "order": 1, "imageTypeCode": "GEN"}, {"path": ""}],
    "reviews": [{"type": "HOTELBEDS", "rate": 4.3, "reviewCount": 812}],
    "facilities": [{"facilityCode": 260, "facilityGroupCode": 70, "timeFrom": "15:00",
                    "description": {"content": "Check-in hour"}},
                   {"facilityCode": 550, "facilityGroupCode": 70, "indYesOrNo": True, "indFee": False}],
    "interestPoints": [{"poiName": "Notre-Dame", "distance": "900"}],
    "terminals": [{"terminalCode": "CDG", "distance": 28}],
    "rooms": [{"roomCode": "DBL.ST", "maxPax": 2, "maxAdults": 2, "maxChildren": 1,
               "roomFacilities": [{"description": {"content": "Balcony"}}, {"facilityCode": 1}]}],
    "lastUpdate": "2026-10-01",
}
r = content_record(HB_HOTEL)
check(r["code"] == "12345" and r["city"] == "PARIS" and r["address"] == "12 Rue Exemple" and r["postalCode"] == "75004",
      "the record keeps code, city, address and postal code (city.content / address.content)")
check(r["coordinates"] == {"lat": 48.859, "lng": 2.362}, "coordinates as {lat, lng}")
check([i["path"] for i in r["images"]] == ["00/012345/b.jpg", "00/012345/a.jpg"] and r["images"][0]["roomCode"] == "DBL.ST",
      "images keep path, order and roomCode; an image without a path is dropped")
check(r["reviews"] == [{"type": "HOTELBEDS", "rate": 4.3, "reviewCount": 812}], "reviews are kept")
check(r["facilities"][0] == {"facilityCode": 260, "facilityGroupCode": 70, "timeFrom": "15:00", "description": "Check-in hour"}
      and r["facilities"][1]["indYesOrNo"] is True, "facilities keep code, group, flags, times and description")
check(r["rooms"] == [{"roomCode": "DBL.ST", "maxPax": 2, "maxAdults": 2, "maxChildren": 1, "facilities": ["Balcony", "1"]}],
      "rooms keep occupancy and their features")
check(r["phones"] == [{"phoneNumber": "+33 1 00", "phoneType": "PHONEBOOKING"}] and len(r["description"]) == 2000,
      "an empty phone is dropped; the description is capped")
check(r["interestPoints"] == [{"poiName": "Notre-Dame", "distance": 900.0}] and r["terminals"][0]["terminalCode"] == "CDG",
      "nearby places and terminals with distances")
check(content_record({"name": "no code"})["code"] == "", "a hotel without a code has an empty code (and is skipped)")


def portfolio(total):
    def fetch(params):
        fetch.calls.append(dict(params))
        if "codes" in params:
            codes = params["codes"].split(",")
            return True, 200, {"hotels": [{"code": c} for c in codes], "total": len(codes)}
        start, end = params["from"], min(params["to"], total)
        return True, 200, {"hotels": [{"code": n} for n in range(start, end + 1)], "total": total}
    fetch.calls = []
    return fetch


def saver(fail_after=None):
    def save(records):
        save.batches.append([rec["code"] for rec in records])
        if fail_after is not None and len(save.batches) > fail_after:
            return 0, "firestore commit HTTP 503: unavailable"
        return len(records), None
    save.batches = []
    return save


# A full load across runs: 1,200 hotels, 500 a page, 2 pages per run.
fetch, save = portfolio(1200), saver()
s1, rep1 = run_sync("auto", {}, fetch, save, "2026-10-21", "T1", max_pages=2, page_size=500)
check(rep1["mode"] == "auto:full" and rep1["pages"] == 2 and rep1["written"] == 1000 and not rep1["done"],
      "auto with no state starts the full load; a run is bounded by max_pages")
check(s1["full_next_from"] == 1001 and s1["full_started_on"] == "2026-10-21" and "full_completed_at" not in s1,
      "the cursor is saved where the run stopped")
check([c["from"] for c in fetch.calls] == [1, 501] and all(c["to"] - c["from"] == 499 for c in fetch.calls)
      and all(c["fields"] == "all" and c["language"] == "ENG" for c in fetch.calls),
      "pages of page_size hotels, all fields, English")
s2, rep2 = run_sync("auto", s1, fetch, save, "2026-10-22", "T2", max_pages=2, page_size=500)
check(rep2["done"] and rep2["written"] == 200 and s2["full_completed_at"] == "T2" and "full_next_from" not in s2,
      "the next run continues from the cursor and finishes the load")
check(s2["full_started_on"] == "2026-10-21", "the load remembers the day it started (where the first delta begins)")

# Then the daily delta.
fetch = portfolio(30)
s3, rep3 = run_sync("auto", s2, fetch, save, "2026-10-23", "T3", max_pages=5, page_size=500)
check(rep3["mode"] == "auto:delta" and rep3["done"] and fetch.calls[0]["lastUpdateTime"] == "2026-10-21",
      "once loaded, auto fetches only what changed since the day the full load started")
check(s3["delta_since"] == "2026-10-23" and "delta_run_on" not in s3, "the next delta starts from this one's day")
fetch = portfolio(10)
s3b, rep3b = run_sync("auto", s3, fetch, save, "2026-10-23", "T3b")
check(rep3b["stopped"] == "already refreshed today" and fetch.calls == [] and s3b == s3,
      "an hourly run on a day already refreshed calls nothing and changes nothing")
s4, _ = run_sync("auto", s3, fetch, save, "2026-10-24", "T4")
check(fetch.calls[0]["lastUpdateTime"] == "2026-10-23", "each delta asks for changes since the previous one")

# A delta interrupted halfway keeps its start day and cursor.
fetch = portfolio(1200)
s5, rep5 = run_sync("delta", s4, fetch, save, "2026-10-25", "T5", max_pages=1, page_size=500)
check(not rep5["done"] and s5["delta_next_from"] == 501 and s5["delta_run_on"] == "2026-10-25"
      and s5["delta_since"] == "2026-10-24", "an unfinished delta keeps its cursor and the day it began")
s6, rep6 = run_sync("delta", s5, fetch, save, "2026-10-26", "T6", max_pages=5, page_size=500)
check(rep6["done"] and fetch.calls[1]["from"] == 501 and s6["delta_since"] == "2026-10-25",
      "it resumes, and the next delta starts from the day the interrupted one began")
fetch = portfolio(1200)
s5b, rep5b = run_sync("auto", dict(s5, delta_since="2026-10-25"), fetch, save, "2026-10-25", "T5b", max_pages=1, page_size=500)
check(fetch.calls and fetch.calls[0]["from"] == 501, "an unfinished delta is resumed even on the same day")

# HotelBeds refuses (e.g. a request quota): stop, keep the cursor, write nothing.
def refused(params):
    return False, 429, {"error": "quota exceeded"}
save = saver()
s7, rep7 = run_sync("full", {"full_next_from": 1501, "full_started_on": "2026-10-20"}, refused, save, "2026-10-21", "T7")
check(rep7["stopped"] == "HotelBeds HTTP 429" and s7["full_next_from"] == 1501 and save.batches == [],
      "a HotelBeds refusal stops the run, keeps the cursor and writes nothing")
check(rep7["error"] == "quota exceeded", "the refusal's reason is reported")

# Firestore fails mid-run: the cursor stays at the page that was not saved.
save = saver(fail_after=1)
s8, rep8 = run_sync("full", {}, portfolio(5000), save, "2026-10-21", "T8", max_pages=5, page_size=500)
check(rep8["stopped"] == "firestore" and s8["full_next_from"] == 501 and rep8["written"] == 500,
      "a Firestore failure stops the run at the unsaved page")

# The time budget.
ticks = iter(range(0, 10000, 100))
s9, rep9 = run_sync("full", {}, portfolio(5000), saver(), "2026-10-21", "T9", max_pages=50, page_size=500,
                    max_seconds=250, clock=lambda: next(ticks))
check(rep9["stopped"] == "time budget" and rep9["pages"] == 2, "a run stops at its time budget")

# Specific codes.
fetch = portfolio(0)
s10, rep10 = run_sync("codes", {"x": 1}, fetch, saver(), "2026-10-21", "T10", codes=["1", " 2 ", ""])
check(fetch.calls[0]["codes"] == "1,2" and rep10["written"] == 2 and rep10["done"], "codes mode loads just those hotels")
check(run_sync("delta", {}, portfolio(1), saver(), "d", "n")[1]["error"].startswith("no full load"),
      "a delta before any full load is refused")
check(run_sync("codes", {}, portfolio(1), saver(), "d", "n")[1]["error"] == "mode codes needs codes",
      "codes mode without codes is refused")

# save_hotels: batches of 100, one document per hotel, the record as `json`.
base_routes()
commits = []
routes["documents:commit"] = lambda u, b: (commits.append(b), {})[1]
written, err = save_hotels("proj", "(default)", "t", [content_record({"code": n, "city": {"content": "PARIS"}})
                                                     for n in range(250)], "2026-10-21T00:00:00Z", "test")
check(written == 250 and err is None and [len(c["writes"]) for c in commits] == [100, 100, 50],
      "Firestore writes go 100 per commit")
w = commits[0]["writes"][0]["update"]
check(w["name"] == "projects/proj/databases/(default)/documents/hotelbeds_content/0"
      and json.loads(w["fields"]["json"]["stringValue"])["city"] == "PARIS"
      and w["fields"]["city"]["stringValue"] == "PARIS" and w["fields"]["source_env"]["stringValue"] == "test",
      "one document per hotel code, the record in `json`, a few plain fields beside it")
routes["documents:commit"] = lambda u, b: (500, {"error": "boom"})
written, err = save_hotels("proj", "(default)", "t", [content_record({"code": 1})], "now", "test")
check(written == 0 and err and err.startswith("firestore commit HTTP 500"), "a failed commit is reported, not swallowed")

# The playbook end to end: state read, sync, state written; no other HotelBeds API.
base_routes()
state_store = {}
routes["hotelbeds_content_sync/state"] = lambda u, b: (404, {}) if not state_store else {"fields": {"json": {"stringValue": json.dumps(state_store)}}}
def commit(u, b):
    for wr in b["writes"]:
        if wr["update"]["name"].endswith("hotelbeds_content_sync/state"):
            state_store.clear()
            state_store.update(json.loads(wr["update"]["fields"]["json"]["stringValue"]))
    return {}
routes["documents:commit"] = commit
routes["hotel-content-api/1.0/hotels"] = lambda u, b: {"hotels": [HB_HOTEL], "total": 1}
g = dict(mode="auto", codes=[], max_pages=3, page_size=500, max_seconds=240, hotelbeds_env="test",
         hotelbeds_api_base="https://api.test.hotelbeds.com", google_project="proj",
         hotelbeds_secret_name="hotelbeds-hotels-test", firestore_database="(default)")
exec(sync_steps["sync"]["tool"]["code"], g)
res = g["result"]
check(res["status"] == "ok" and res["report"]["done"] and state_store.get("full_completed_at"),
      "the playbook run loads, finishes and saves its state: %s" % json.dumps(res)[:200])
before = dict(state_store)
g2 = dict(g, mode="codes", codes=["12345"])
exec(sync_steps["sync"]["tool"]["code"], g2)
check(g2["result"]["report"]["written"] == 1 and state_store == before, "codes mode loads the hotels and leaves the load's state alone")
hb_urls = [u for _, u, _ in calls if "hotelbeds.com" in u]
check(hb_urls and all("/hotel-content-api/1.0/hotels?" in u for u in hb_urls),
      "the sync calls only the Content API hotels list (no availability or booking)")

# ── The planner's search reads the copy ──────────────────────────────────

planner = {s["step"]: s for s in yaml.safe_load(open("playbooks/itinerary-planner.yaml"))["workflow"]}
search_step = planner["call_hotelbeds_hotels"]["tool"]
check(search_step["code"] == planner["call_hotelbeds_book"]["tool"]["code"], "both planner HotelBeds steps carry the same code")
for name in ("call_hotelbeds_hotels", "call_hotelbeds_book"):
    inp = planner[name]["tool"]["input"]
    check(inp.get("hotel_content_source") == "cache" and inp.get("firestore_database") == "(default)",
          "%s reads content from the cache by default" % name)

AVAIL = {"hotels": {"total": 2, "hotels": [
    {"code": 12345, "name": "Hotel Example", "currency": "EUR", "minRate": "400.00", "rooms": []},
    {"code": 999, "name": "Not Cached", "currency": "EUR", "minRate": "300.00", "rooms": []}]}}
CACHED = content_record(HB_HOTEL)


def search(source="cache", firestore=None):
    base_routes()
    routes["hotel-api/1.0/hotels"] = lambda u, b: AVAIL
    routes["hotel-content-api/1.0/hotels"] = lambda u, b: {"hotels": [{"code": 12345, "images": [{"path": "live/x.jpg"}]}]}
    routes[":batchGet"] = firestore or (lambda u, b: [
        {"found": {"name": d, "fields": {"json": {"stringValue": json.dumps(CACHED)}}}} if d.endswith("/12345")
        else {"missing": d} for d in b["documents"]] + [
        {"found": {"name": "projects/proj/databases/(default)/documents/hotelbeds_content/777",
                   "fields": {"json": {"stringValue": json.dumps(dict(CACHED, code="777"))}}}}])
    g = dict(method="tools/call", tool="search_hotels", book_tolerance=15, max_hotels=10,
             arguments={"latitude": 48.85, "longitude": 2.35, "check_in": "2026-11-03", "check_out": "2026-11-07"},
             hotelbeds_env="test", hotelbeds_api_base="https://api.test.hotelbeds.com", google_project="proj",
             hotelbeds_secret_name="hotelbeds-hotels-test", hotel_content_source=source, firestore_database="(default)")
    exec(search_step["code"], g)
    blob = json.dumps(g["result"])
    data = json.loads(blob)
    hotels = None
    def find(o):
        nonlocal hotels
        if isinstance(o, dict):
            if isinstance(o.get("hotels"), list) and o["hotels"] and isinstance(o["hotels"][0], dict) and "code" in o["hotels"][0]:
                hotels = hotels or o
            for v in o.values():
                find(v)
        elif isinstance(o, list):
            for v in o:
                find(v)
    find(data)
    return hotels or {}, calls[:]


out, seen = search()
by_code = {str(h["code"]): h for h in out.get("hotels", [])}
check(not any("hotel-content-api" in u for _, u, _ in seen), "a cached search makes no Content API request")
gets = [b for m, u, b in seen if u.endswith(":batchGet")]
check(len(gets) == 1 and gets[0]["documents"] == ["projects/proj/databases/(default)/documents/hotelbeds_content/12345",
                                                  "projects/proj/databases/(default)/documents/hotelbeds_content/999"]
      and gets[0]["mask"] == {"fieldPaths": ["json"]}, "one Firestore batchGet for the search's hotel codes")
check(by_code["12345"]["images"] == ["https://photos.hotelbeds.com/giata/bigger/00/012345/a.jpg",
                                     "https://photos.hotelbeds.com/giata/bigger/00/012345/b.jpg"],
      "photos come from the copy, in HotelBeds' order")
check(by_code["999"]["images"] == [], "a hotel not in the copy has no photos (no live fallback)")
check("777" not in json.dumps(out), "a document for a code the search did not ask for is ignored")
check(by_code["12345"].get("city") == "PARIS" and by_code["12345"].get("address") == "12 Rue Exemple"
      and by_code["12345"].get("postalCode") == "75004" and "city" not in by_code["999"],
      "the copy's address, city and postal code ride along for cached hotels only")
meta = out.get("meta") or {}
check(meta.get("content_cache") == {"source": "cache", "requested": 2, "hits": 1, "misses": 1, "error": None},
      "the search reports cache hits and misses: %s" % meta.get("content_cache"))

out, seen = search(firestore=lambda u, b: (503, {"error": "down"}))
check(len(out.get("hotels", [])) == 2 and all(h["images"] == [] for h in out["hotels"])
      and (out.get("meta") or {}).get("content_cache", {}).get("error"),
      "Firestore down: the search still returns its hotels, without photos, and says why")
check(not any("hotel-content-api" in u for _, u, _ in seen), "...and still makes no Content API request")

out, seen = search(source="live")
check(any("hotel-content-api" in u for _, u, _ in seen) and not any(u.endswith(":batchGet") for _, u, _ in seen)
      and {str(h["code"]): h for h in out["hotels"]}["12345"]["images"] == ["https://photos.hotelbeds.com/giata/bigger/live/x.jpg"],
      "hotel_content_source=live is the old per-search call (rollback only)")
out, seen = search(source="off")
check(not any("hotel-content-api" in u or u.endswith(":batchGet") for _, u, _ in seen)
      and all(h["images"] == [] for h in out["hotels"]), "hotel_content_source=off fetches no content at all")
out, seen = search(source="bogus")
check(any(u.endswith(":batchGet") for _, u, _ in seen), "an unknown source falls back to the cache, never to live")

if failures:
    sys.exit("%d failure(s)" % len(failures))
