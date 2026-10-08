#!/usr/bin/env python3
"""The business catalog's WRITE path, proven offline.

``playbooks/catalog/items/upsert.yaml`` — see
``docs/architecture/business-catalog-firestore.md``.

⚠ WHY: only the READ path (``catalog/items/list``) had ever been proven. A catalog you can
only read is not a catalog — nothing had ever been written to ``catalog/items`` in
Firestore, so the collections did not exist and the whole domain model was a design doc.

Runs the playbook's own embedded code against the real domain fixture. No network.

The assertion that matters is the **ancestor closure**. Firestore has no recursive query,
so "every item under Beach" can only be one ``array-contains`` if the whole ancestor path
was materialised at WRITE time. An item on a leaf category that is NOT findable from the
root is the failure, and it is silent: the query returns fewer rows and looks fine.
"""
import json
import sys

import yaml

PLAYBOOK = "playbooks/catalog/items/upsert.yaml"
FIXTURE = "qa/fixtures/business-catalog-domain.json"
steps = {s["step"]: s for s in yaml.safe_load(open(PLAYBOOK))["workflow"]}
fx = json.load(open(FIXTURE))

failures = []
checks = 0


def check(label, got, expect):
    global checks
    checks += 1
    ok = got == expect
    print("  %-58s got=%-26s want=%-20s %s" % (label, str(got)[:26], str(expect)[:20],
                                               "OK" if ok else "FAIL"))
    if not ok:
        failures.append(label)


def run(step, **inputs):
    env = dict(inputs)
    exec(steps[step]["tool"]["code"], env)  # noqa: S102
    return env["result"]


# ------------------------------------------------------------------ the gate
print("the child dispatch must block for its result")
tl = steps["persist"]["tool"]
check("return_result set", tl.get("return_result"), True)
check("result_step named", tl.get("result_step"), "firestore_dispatch")
check("timeout is an int", isinstance(tl.get("timeout"), int), True)
check("`start` step exists", "start" in steps, True)

# ------------------------------------------------------------- build_documents
print("\nbuild_documents")
r = run("build_documents", items=fx["items"], categories=fx["categories"],
        collection_root="catalog")
paths = set(r["paths"])
check("document count matches the path set", r["document_count"], len(paths))
check("items counted", r["item_count"], 4)
check("categories counted", r["category_count"], 4)

# 4 category docs + 7 category content docs (2+2+2+1)
# 4 item docs + 7 item content docs (3+1+2+1) + 1 image + 1 unit
check("every expected document is produced", r["document_count"], 4 + 7 + 4 + 7 + 1 + 1)
check("an item doc path", "catalog/items/itm_malaga_beach" in paths, True)
check("a localized content path", "catalog/items/itm_malaga_beach/content/ka" in paths, True)
check("an image subcollection path", "catalog/items/itm_malaga_beach/images/img_1" in paths, True)
check("a unit subcollection path", "catalog/items/itm_malaga_beach/units/unit_7" in paths, True)
check("a category content path", "catalog/categories/cat_beach/content/de" in paths, True)

docs = {d["path"]: d["doc"] for d in r["set_docs"]}
check("batch items use the `doc` key", all("doc" in d for d in r["set_docs"]), True)

# ---------------------------------------------- THE ancestor closure assertion
print("\nthe hierarchy closure — the one transformation Firestore cannot do at read time")
leaf = docs["catalog/categories/cat_beach_family"]
check("leaf category's ancestors", leaf["ancestor_ids"], ["cat_beach", "cat_root"])
check("  and its depth", leaf["depth"], 2)
check("root has no ancestors", docs["catalog/categories/cat_root"]["ancestor_ids"], [])

itm = docs["catalog/items/itm_malaga_beach"]
check("an item on the LEAF carries the whole closure",
      itm["category_ids"], ["cat_beach", "cat_beach_family", "cat_root"])
check("  its primary category is the DIRECT one, not an ancestor",
      itm["primary_category_id"], "cat_beach_family")
check("an item on a mid node closes to the root",
      docs["catalog/items/itm_malaga_tour"]["category_ids"], ["cat_beach", "cat_root"])
check("a city item does NOT gain the beach ancestors",
      docs["catalog/items/itm_madrid_flat"]["category_ids"], ["cat_city", "cat_root"])

# available_langs is what lets the read path pick a language without a second query
check("available_langs is denormalised onto the item",
      itm["available_langs"], ["de", "en", "ka"])
check("  and a single-language item reports just the one",
      docs["catalog/items/itm_malaga_tour"]["available_langs"], ["en"])
check("content documents carry their own lang_code",
      docs["catalog/items/itm_malaga_beach/content/de"]["lang_code"], "de")
check("the EAV attrs map survives", itm["attrs"]["star_rating"], 4)
check("a draft item is still written, with its status",
      docs["catalog/items/itm_draft_hidden"]["status"], "draft")

# -------------------------------------------------------------------- refusals
print("\nrefusals")
for bad, why in (({"items": [{"item_type": "lodging"}], "categories": []}, "item with no item_id"),
                 ({"items": [], "categories": [{"parent_id": None}]}, "category with no category_id")):
    try:
        run("build_documents", collection_root="catalog", **bad)
        check(why + " is refused", False, True)
    except ValueError:
        check(why + " is refused", True, True)

# the 500-write batch limit must REFUSE, not truncate
many = [{"item_id": "i%d" % i, "content": {"en": {"name": "x"}}} for i in range(300)]
try:
    run("build_documents", items=many, categories=[], collection_root="catalog")
    check("over 500 documents is refused, not truncated", False, True)
except ValueError as e:
    check("over 500 documents is refused, not truncated", "500" in str(e), True)

# ---------------------------------------------------------------------- report
print("\nreport — the count is COMPARED, not just echoed")
env = {"isError": False, "data": {"set_docs": {"succeeded": r["document_count"], "failed": 0}}}
rep = run("report", expected=r["document_count"], paths=r["paths"],
          item_count=4, category_count=4, write_result=env)
check("counts agree on a full write", rep["counts_agree"], True)
check("  and the expected count is published", rep["expected_documents"], r["document_count"])

# ---------------------------------------------------------------- RED CONTROL
# A partial write returns a SUCCESS envelope. The count is the only thing that says so,
# which is why `report` compares rather than echoes.
print("\nRED CONTROL — a partial write must not read as success")
short = {"isError": False, "data": {"set_docs": {"succeeded": 3, "failed": 0}}}
rep2 = run("report", expected=r["document_count"], paths=r["paths"],
           item_count=4, category_count=4, write_result=short)
check("3 of %d is NOT agreement (control)" % r["document_count"], rep2["counts_agree"], False)
check("  and the shortfall is visible (control)", rep2["written_documents"], 3)
empty = run("report", expected=r["document_count"], paths=[], item_count=0, category_count=0,
            write_result={})
check("an empty envelope is NOT agreement (control)", empty["counts_agree"], False)

print("\n%d checks, %d failed" % (checks, len(failures)))
if failures:
    for f in failures:
        print("  FAILED: %s" % f)
    sys.exit(1)
print("PASS")
