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

test("OI ranking exposes a desktop scrollbar and hides it on mobile", () => {
  assert.match(
    css,
    /\.ranking-wrap\s*\{[^}]*scrollbar-width:\s*auto;/s,
  );
  assert.match(
    css,
    /\.ranking-wrap::\-webkit-scrollbar\s*\{[^}]*height:\s*12px;/s,
  );
  assert.match(
    css,
    /\.oi-table\s*\{[^}]*min-width:\s*1786px;/s,
  );
  assert.match(
    css,
    /@media \(max-width:\s*640px\)[\s\S]*?\.ranking-wrap\s*\{[^}]*scrollbar-width:\s*none;[\s\S]*?\.oi-table\s*\{[^}]*min-width:\s*100%;/,
  );
  assert.doesNotMatch(
    css,
    /\.ranking-wrap::\-webkit-scrollbar\s*,\s*\.signal-wrap::\-webkit-scrollbar/,
  );
});
