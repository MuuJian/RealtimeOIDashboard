import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(
  new URL(
    "../realtime_oi_dashboard/static/css/tables.css",
    import.meta.url,
  ),
  "utf8",
);
const cellCss = readFileSync(
  new URL(
    "../realtime_oi_dashboard/static/css/table-cells.css",
    import.meta.url,
  ),
  "utf8",
);
const dashboardCss = readFileSync(
  new URL(
    "../realtime_oi_dashboard/static/css/dashboard.css",
    import.meta.url,
  ),
  "utf8",
);

test("OI ranking exposes a desktop scrollbar and hides it on mobile", () => {
  assert.match(
    css,
    /\.ranking-wrap\s*\{[^}]*scrollbar-width:\s*none;/s,
  );
  assert.match(
    css,
    /\.ranking-wrap::\-webkit-scrollbar\s*\{[^}]*display:\s*none;/s,
  );
  assert.match(
    css,
    /\.oi-table\s*\{[^}]*min-width:\s*1786px;/s,
  );
  assert.match(
    css,
    /\.ranking-horizontal-scroll\s*\{[^}]*display:\s*flex;/s,
  );
  assert.match(
    css,
    /\.ranking-horizontal-scroll\[hidden\]\s*\{[^}]*display:\s*none;/s,
  );
  assert.match(
    css,
    /\.ranking-horizontal-thumb\s*\{[^}]*background:\s*var\(--green-ink\);/s,
  );
  assert.match(
    cellCss,
    /@media \(min-width:\s*1792px\)[\s\S]*?\.oi-table\s*\{[^}]*min-width:\s*100%;/,
  );
  assert.match(
    css,
    /@media \(max-width:\s*640px\)[\s\S]*?\.oi-table\s*\{[^}]*min-width:\s*100%;[\s\S]*?\.ranking-horizontal-scroll\s*\{[^}]*display:\s*none;/,
  );
});

test("stable profile keeps the optimized 13-column OI table", () => {
  assert.match(
    dashboardCss,
    /data-dashboard-profile="stable"[^}]*\.oi-table\s*\{[^}]*min-width:\s*1586px;/s,
  );
  assert.match(
    dashboardCss,
    /@media \(min-width:\s*1592px\)[\s\S]*?data-dashboard-profile="stable"[^}]*\.oi-table\s*\{\s*min-width:\s*100%;/,
  );
  assert.match(
    dashboardCss,
    /data-dashboard-profile="stable"[^}]*\.oi-table td:nth-child\(13\)\s*\{\s*width:\s*90px;/,
  );
});
