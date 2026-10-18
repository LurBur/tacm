// TACM Operations Console static guardrails. No third-party dependencies.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html=readFileSync("docs/crypto-governor/index.html","utf8");
const redirect=readFileSync("docs/crypto-governor/forward.html","utf8");
const start=html.indexOf("<script>"),stop=html.lastIndexOf("</script>");
assert(start>=0 && stop>start,"Self-contained JavaScript must exist");
new vm.Script(html.slice(start+8,stop),{filename:"tacm-operations-console.js"});

for(const id of [
  "mBTC","mETH","refreshBtn","freshDot","freshText",
  "kPrice","kEquity","kReturn","kDelta","kExposure","kCoverage","kCoverageMeta",
  "primaryChart","viewMarket","viewEquity","lastPrice",
  "actionHeadline","actionDetail","decisionAt","phaseDetail",
  "strCrystal","strFlower","strFlame","strCrystalV","strFlowerV","strFlameV",
  "agentRows","gateLabel","gateDesc","scoreRows","eventRows","warning"
]){
  assert(html.includes('id="'+id+'"'),"Required operational element missing: "+id);
}
assert(html.includes("background:var(--bg)") && html.includes("--bg:#050607"),"Use true black console canvas");
assert(html.includes("grid-template-columns:repeat(6,minmax(0,1fr))"),"Six glanceable KPIs");
assert(html.includes("grid-template-columns:minmax(0,1.7fr) minmax(310px,.81fr)"),"Chart/rail desktop grid");
assert(html.includes("OBSERVER_BASE+\'/v1/forward/\'") && html.includes("OBSERVER_BASE+\'/v1/data/\'"),"Use persistent Railway v1 forward records and completed Kraken candles");
assert(html.includes("state.last_hash!==events.at(-1)?.hash"),"Validate journal/state checkpoint");
assert(html.includes("events[i].prev_hash"),"Check journal continuity");
assert(html.includes("skipped_unobserved_hours"),"Expose missing observations");
assert(html.includes("prev_strengths"),"Read persisted TACM strengths");
assert(html.includes("SMA 12") && html.includes("SMA 48"),"Market chart must show transparent indicators");
assert(html.includes("setInterval"),"Refresh from public paper logs");
assert(html.includes("prefers-reduced-motion"),"Respect reduced motion preferences");
assert(html.includes("PAPER · PILOT"),"Make simulation/pilot mode clearly visible");
assert(html.includes("DIAGNOSTIC PILOT"),"Do not misstate evidence validity");
assert(!html.includes("UI goal") && !html.includes("Best next") && !html.includes("What this means"),
       "Do not publish design commentary on the operator UI");
assert(html.includes("wss://ws.kraken.com/v2"),"Unauthenticated public Kraken ticker socket must exist");
assert(html.includes("event_trigger:'bbo'"),"Use public best bid/ask changes");
assert(html.includes("PAPER QUOTE ·"),"Label historical paper quote age distinctly");
assert(html.includes("LIVE KRAKEN · PUBLIC BID / ASK"),"Live price must identify its source");
assert(html.includes("RAILWAY V1 / DIAGNOSTIC PILOT"),"Display prospective hosted observer and experimental validity");
assert(html.includes("OBSERVER_BASE+\'/health\'"),"Check hosted observer health before displaying paper data");
assert(html.includes("PAPER OBSERVER OFFLINE"),"Do not fake paper metrics when observer is down");
assert(html.includes("PAPER PAUSED · SCHEDULER GAP"),"Never present a gap-related halt as normal activity");
assert(html.includes("renderPublicQuote"),"Live quote renderer must be isolated");
assert(!html.includes("onchainTransaction"),"Live UI must not submit onchain transactions");
assert(!html.includes("api.kraken.com/0/private"),"No private exchange order endpoints");
assert(!html.includes("Place order"),"This interface has no real trading controls");
assert(redirect.includes('http-equiv="refresh"') && redirect.includes("url=./"),"Keep just one live dashboard");
console.log("TACM black operator console: JS syntax + single-page/market-data guardrails passed");
