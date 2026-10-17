// Smoke tests for single-page TACM Frontier Console (no external test dependencies).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync("docs/crypto-governor/index.html", "utf8");
const old = readFileSync("docs/crypto-governor/forward.html", "utf8");
const start = html.indexOf("<script>");
const end = html.lastIndexOf("</script>");
assert(start >= 0 && end > start, "Frontier page must have a locally parseable script");
const script = html.slice(start + "<script>".length, end);
new vm.Script(script, {filename:"TACM Frontier Console inline JS"});
for(const id of ["coverageBig","coverageFill","coverageNote","healthMetrics","symbolSelect","stageMarket",
"stageAgents","stageSupervisor","stageRisk","stageLedger","scoreRows","eventsList","chartSvg",
"reloadBtn","lastRefresh","tickerTrack","heroSymbol"]){
  assert(html.includes('id="'+id+'"'), "Missing live-data element "+id);
}
assert(html.includes("./forward/"), "Relative forward paper ledger data is required");
assert(html.includes("PLOT_KEYS"), "Supervisor equity comparison is required");
assert(html.includes("setInterval"), "The display must periodically refresh");
assert(html.includes("prefers-reduced-motion"), "Respect motion sensitivity");
assert(html.includes("grid-template-columns: repeat(4, minmax(0, 1fr) 14px)"),
  "Five-stage animated pipeline should fit on one desktop row");
assert(html.includes("events.at(-1).hash !== state.last_hash"), "State / journal mismatch guard required");
assert(html.includes("one") || html.includes("One"), "Describe the one-decision-per-hour research rule");
assert(!html.includes("api.kraken.com/0/private"), "No authenticated exchange API in UI");
assert(!html.includes("Place order"), "Research UI must have no trading controls");
assert(old.includes('http-equiv="refresh"') && old.includes('url=./'), "Old URL must redirect");
assert(!old.includes('id="scoreRows"'), "Old dashboard must not coexist");
console.log("TACM Frontier static/JS checks passed.");
