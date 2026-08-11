import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const index = readFileSync(
  new URL("../realtime_oi_dashboard/index.html", import.meta.url),
  "utf8",
);
const icon = readFileSync(
  new URL(
    "../realtime_oi_dashboard/static/favicon.svg",
    import.meta.url,
  ),
  "utf8",
);

test("dashboard exposes a compact branded SVG favicon", () => {
  assert.match(
    index,
    /<link rel="icon" type="image\/svg\+xml" href="\/static\/favicon\.svg\?v=4">/,
  );
  assert.match(index, /<meta name="theme-color" content="#090c13">/);
  assert.match(icon, /<svg[^>]*viewBox="90 90 168 168"/);
  assert.match(icon, /fill="rgb\(33,51,119\)"/);
  assert.equal((icon.match(/<path\b/g) ?? []).length, 3);
  assert.doesNotMatch(icon, /#56e7ff/);
  assert.doesNotMatch(icon, /#2bdc8a/);
  assert.doesNotMatch(icon, /<(?:metadata|script|foreignObject)\b/i);
  assert.doesNotMatch(icon, /<(?:script|foreignObject)\b/i);
});
