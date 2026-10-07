#!/usr/bin/env python3
"""Regression test for the Firestore BUSINESS catalog read path.

``playbooks/catalog/items/list.yaml`` -- see
``docs/architecture/business-catalog-firestore.md``.

Runs the playbook's OWN embedded code against fixtures shaped like the REGISTERED
Firestore MCP connector (``automation/agents/mcp/firestore`` v11), in the style of
``profile_read_only_test.py``. No network, no credentials, no Firestore.

Why this test exists: the connector returns TWO different response shapes and the
first draft of the playbook used the wrong one.

  * ``query_collection`` -> ``{collection_path, count, documents: [...]}``
  * ``batch_get_docs``   -> ``{count, succeeded, failed, results: [...], by_path: {...}, errors: []}``

Reading ``documents`` from a ``batch_get_docs`` reply yields an empty join, and an
empty join is indistinguishable from "no item has a translation" -- a silent false
zero on every item in the catalogue. The RED CONTROL at the bottom feeds exactly that
wrong shape and asserts the test notices; a test that cannot fail here is worthless,
because the bug it guards against produces a clean-looking result.

It also pins the tool kind. ``kind: agent`` is NOT one of the server's 25 ToolKind
variants -- it is in the explicit reject list -- so a playbook using it can never
run. noetl/travel#134.
"""
import glob
import sys

import yaml

PLAYBOOK = "playbooks/catalog/items/list.yaml"
CALENDAR = "playbooks/catalog/calendar/list.yaml"

doc = yaml.safe_load(open(PLAYBOOK))
steps = {s["step"]: s for s in doc["workflow"]}

failures = []
checks = 0


def check(label, got, expect):
    global checks
    checks += 1
    ok = got == expect
    print("  %-62s expect=%-6s got=%-6s %s" % (label, expect, got, "OK" if ok else "FAIL"))
    if not ok:
        failures.append(label)


def run(step_name, **inputs):
    """Execute one python step's embedded code and return its ``result``."""
    code = steps[step_name]["tool"]["code"]
    env = dict(inputs)
    exec(code, env)  # noqa: S102 - running the playbook's own code is the point
    return env["result"]


# ------------------------------------------------- the runtime's own entry gate
# A playbook with no step named `start` is rejected at PARSE time with
# "Workflow must have a step named 'start'" (server src/playbook/parser.rs:184),
# BEFORE any tool kind is looked at. Two consequences, both learned the hard way:
#
#   * `catalog/calendar/list`'s `kind: agent` defect was MASKED by this -- the
#     playbook failed for the earlier reason, so fixing the tool kind alone left
#     it just as unrunnable.
#   * The first draft of `catalog/items/list` -- written with 29 passing checks --
#     had the same omission. Those checks exec each step's embedded code and never
#     ask the runtime to accept the workflow, so a guard over step BODIES cannot
#     see a whole-WORKFLOW rule. Only an actual execution did, as a 422.
#
# So this covers EVERY playbook in the repo, not only the catalog ones; the
# measured ratio when it was written was 2 of 7 missing. The count is asserted
# because a glob matching nothing would otherwise report a clean pass.
print("the runtime's entry gate: every playbook needs a step named `start`")
ALL_PLAYBOOKS = sorted(glob.glob("playbooks/**/*.yaml", recursive=True))
check("found a plausible number of playbooks to check", len(ALL_PLAYBOOKS) >= 4, True)
for pb in ALL_PLAYBOOKS:
    wf = yaml.safe_load(open(pb)).get("workflow") or []
    names = [s.get("step") for s in wf if isinstance(s, dict)]
    check("%s has a `start` step" % pb.replace("playbooks/", ""), "start" in names, True)

# ------------------------------------------------------------------ tool kinds
print("\ntool kinds (noetl/travel#134 -- `agent` is in the server's reject list)")
REJECTED = {"agent", "mcp", "provider", "result_fetch"}
for path in (PLAYBOOK, CALENDAR):
    kinds = [s["tool"].get("kind") for s in yaml.safe_load(open(path))["workflow"]]
    bad = sorted(set(kinds) & REJECTED)
    check("%s uses no rejected kind" % path.split("/", 2)[-1], bad, [])

# an MCP provider is reached as a child playbook, with a path
for name, s in steps.items():
    if s["tool"].get("kind") == "playbook":
        check("%s names a child path" % name, bool(s["tool"].get("path")), True)

# ------------------------------------------------------------- validate_inputs
print("\nvalidate_inputs")
r = run("validate_inputs", category_id=" cat_beach ", lang="", limit="100",
        collection_root="catalog")
check("trims the category", r["category_id"], "cat_beach")
check("defaults a blank language to en", r["lang"], "en")
check("builds the items collection", r["items_collection"], "catalog/items")

r = run("validate_inputs", category_id="c", lang="de", limit=9999, collection_root="catalog")
check("clamps limit to the connector's cap", r["limit"], 500)
check("and says that it clamped", r["limit_was_clamped"], True)

try:
    run("validate_inputs", category_id="   ", lang="en", limit=10, collection_root="catalog")
    check("empty category raises", False, True)
except ValueError:
    check("empty category raises", True, True)

# --------------------------------------------------------- resolve_content_paths
print("\nresolve_content_paths (query_collection shape: `documents`)")
def envelope(data):
    """The MCP envelope a `kind: playbook` child hands back, read by the BARE STEP
    NAME. `{{ step.result }}` resolves to nothing and silently yields an empty."""
    return {"isError": False, "summary": "ok", "data": data}


QUERY_REPLY = envelope({
    "collection_path": "catalog/items",
    "count": 3,
    "documents": [
        {"path": "catalog/items/itm_de", "data": {
            "item_type": "lodging", "available_langs": ["en", "de"], "default_lang": "en",
            "attrs": {"has_pool": True}, "price_from": {"amount": 11500, "currency": "EUR"}}},
        {"path": "catalog/items/itm_en_only", "data": {
            "item_type": "tour", "available_langs": ["en"], "default_lang": "en", "attrs": {}}},
        {"path": "catalog/items/itm_no_langs", "data": {
            "item_type": "tour", "default_lang": "ka", "attrs": {}}},
    ],
})
rp = run("resolve_content_paths", lang="de", items_collection="catalog/items",
         query_result=QUERY_REPLY)
check("reads all three documents", rp["item_count"], 3)
check("echoes the returned count", rp["returned_count"], 3)
by_id = {i["item_id"]: i for i in rp["items"]}
check("item declaring de gets de", by_id["itm_de"]["content_lang"], "de")
check("  and is not marked a fallback", by_id["itm_de"]["lang_is_fallback"], False)
check("item without de falls back to its default", by_id["itm_en_only"]["content_lang"], "en")
check("  and IS marked a fallback", by_id["itm_en_only"]["lang_is_fallback"], True)
check("item with no available_langs uses its default", by_id["itm_no_langs"]["content_lang"], "ka")
check("one content path per item", len(rp["content_paths"]), 3)
check("path is parent/content/lang", rp["content_paths"][0]["path"],
      "catalog/items/itm_de/content/de")

# ------------------------------------------------------------------- assemble
print("\nassemble (batch_get_docs shape: `by_path`, NOT `documents`)")
BATCH_REPLY = {
    "count": 3, "succeeded": 3, "failed": 0, "errors": [],
    "results": [
        {"index": 0, "path": "catalog/items/itm_de/content/de", "found": True,
         "document": {"path": "catalog/items/itm_de/content/de",
                      "data": {"name": "Strandhotel", "summary": "am Meer"}}},
        {"index": 1, "path": "catalog/items/itm_en_only/content/en", "found": True,
         "document": {"path": "catalog/items/itm_en_only/content/en",
                      "data": {"name": "City Tour", "summary": "walk"}}},
        # A language that was never translated. 404 -> found=false inside _ok, so the
        # batch SUCCEEDS and the absence is data, not an error.
        {"index": 2, "path": "catalog/items/itm_no_langs/content/ka", "found": False,
         "document": None},
    ],
}
BATCH_REPLY["by_path"] = {r["path"]: r for r in BATCH_REPLY["results"]}
BATCH_REPLY = envelope(BATCH_REPLY)

asm = run("assemble", items=rp["items"], item_count=rp["item_count"],
          items_collection="catalog/items", category_id="cat_beach", lang="de",
          limit_was_clamped=False, content_result=BATCH_REPLY)
names = {i["item_id"]: i["name"] for i in asm["items"]}
check("joins the de translation", names["itm_de"], "Strandhotel")
check("joins the en fallback", names["itm_en_only"], "City Tour")
check("an untranslated item still appears", "itm_no_langs" in names, True)
check("  with a null name rather than being dropped", names["itm_no_langs"], None)
check("counts items", asm["counts"]["items"], 3)
check("counts the ones missing content", asm["counts"]["without_content"], 1)
check("publishes the queried denominator", asm["counts"]["queried"], 3)

# a connector revision that only fills `results` must still work
only_results = envelope({k: v for k, v in BATCH_REPLY["data"].items() if k != "by_path"})
asm2 = run("assemble", items=rp["items"], item_count=3, items_collection="catalog/items",
           category_id="c", lang="de", limit_was_clamped=False, content_result=only_results)
check("falls back to `results` when by_path is absent",
      sum(1 for i in asm2["items"] if i["name"]), 2)

# ------------------------------------------------------------- RED CONTROL
# Feed the WRONG shape -- query_collection's `documents` key on a batch_get_docs
# reply, which is the bug this test was written for. The join must collapse. If this
# control ever reports 2 translations, the test has stopped discriminating and every
# check above is decorative.
print("\nRED CONTROL -- the wrong response key must break the join")
wrong = envelope({"documents": BATCH_REPLY["data"]["results"]})
asm3 = run("assemble", items=rp["items"], item_count=3, items_collection="catalog/items",
           category_id="c", lang="de", limit_was_clamped=False, content_result=wrong)
joined = sum(1 for i in asm3["items"] if i["name"])
check("wrong key joins NOTHING (control)", joined, 0)
check("and every item is reported as missing content (control)",
      asm3["counts"]["without_content"], 3)

print("\nstructural: no step may read a child playbook's output via `.result`")
import re as _re
for pb in ("playbooks/catalog/items/list.yaml", "playbooks/catalog/calendar/list.yaml"):
    doc_all = yaml.safe_load(open(pb))
    kids = [s["step"] for s in doc_all["workflow"] if s["tool"].get("kind") == "playbook"]
    check("%s has child playbook steps" % pb.split("/")[-2], len(kids) >= 1, True)
    body = open(pb).read()
    for cs in kids:
        bad = _re.findall(r"\{\{[^}]*\b%s\.result\b[^}]*\}\}" % _re.escape(cs), body)
        check("  `%s` not read via .result" % cs, bad, [])

print("\n%d checks, %d failed" % (checks, len(failures)))
if failures:
    for f in failures:
        print("  FAILED: %s" % f)
    sys.exit(1)
print("PASS")
