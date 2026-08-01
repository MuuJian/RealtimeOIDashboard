import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import vm from "node:vm";

if (typeof vm.SourceTextModule !== "function") {
  const result = spawnSync(
    process.execPath,
    [
      "--no-warnings",
      "--experimental-vm-modules",
      fileURLToPath(import.meta.url),
      ...process.argv.slice(2),
    ],
    { stdio: "inherit" },
  );
  if (result.error) throw result.error;
  process.exit(result.status ?? 1);
}

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const roots = [join(packageRoot, "static/js")];
const files = roots.flatMap(collectJavaScriptFiles);
const importsByFile = new Map();

for (const file of files) {
  importsByFile.set(file, checkRelativeImports(file));
}

const htmlPath = join(packageRoot, "index.html");
const entryPath = join(packageRoot, "static/js/dashboard.js");
const stylesheetPath = join(packageRoot, "static/css/dashboard.css");
checkIndexEntry(htmlPath, '<script type="module" src="/static/js/dashboard.js"></script>');
checkIndexEntry(htmlPath, '<link rel="stylesheet" href="/static/css/dashboard.css">');
if (!existsSync(stylesheetPath)) {
  throw new Error(`Missing dashboard stylesheet: ${stylesheetPath}`);
}
const stylesheetCount = checkStylesheetImports(stylesheetPath);
checkReachableModules(entryPath, files, importsByFile);
checkDomIds(htmlPath, files);
console.log(
  `Checked ${files.length} reachable dashboard JavaScript files and `
  + `${stylesheetCount} stylesheets.`,
);

function collectJavaScriptFiles(root) {
  return readdirSync(root, { withFileTypes: true }).flatMap(entry => {
    const path = join(root, entry.name);
    if (entry.isDirectory()) return collectJavaScriptFiles(path);
    return entry.isFile() && path.endsWith(".js") ? [path] : [];
  });
}

function checkRelativeImports(file) {
  const source = readFileSync(file, "utf8");
  const module = new vm.SourceTextModule(source, { identifier: file });
  const imports = module.moduleRequests
    ? module.moduleRequests.map(request => request.specifier)
    : module.dependencySpecifiers;
  const workers = [
    ...source.matchAll(
      /new Worker\(\s*new URL\(\s*["']([^"']+)["']\s*,\s*import\.meta\.url\s*\)/g,
    ),
  ].map(match => match[1]);
  const specifiers = [...imports, ...workers];
  const targets = [];

  for (const specifier of specifiers) {
    if (!specifier.startsWith(".")) {
      throw new Error(`Dashboard import must be relative in ${file}: ${specifier}`);
    }

    const target = resolve(dirname(file), specifier);
    if (!existsSync(target)) {
      throw new Error(`Missing import target in ${file}: ${specifier}`);
    }
    targets.push(target);
  }
  return targets;
}

function checkIndexEntry(htmlPath, expectedEntry) {
  const html = readFileSync(htmlPath, "utf8");
  if (!html.includes(expectedEntry)) {
    throw new Error(`${htmlPath} must load ${expectedEntry}`);
  }
}

function checkStylesheetImports(entryPath) {
  const source = readFileSync(entryPath, "utf8");
  const imports = [...source.matchAll(/@import\s+url\(["']([^"']+)["']\)\s*;/g)]
    .map(match => match[1]);
  const stylesheets = new Set([entryPath]);

  for (const specifier of imports) {
    if (!specifier.startsWith(".")) {
      throw new Error(`Dashboard stylesheet import must be relative: ${specifier}`);
    }
    const target = resolve(dirname(entryPath), specifier);
    if (!target.endsWith(".css") || !existsSync(target)) {
      throw new Error(`Missing dashboard stylesheet import: ${specifier}`);
    }
    stylesheets.add(target);
  }
  return stylesheets.size;
}

function checkReachableModules(entryPath, files, importsByFile) {
  const knownFiles = new Set(files);
  const reachable = new Set();
  const pending = [entryPath];

  while (pending.length) {
    const file = pending.pop();
    if (reachable.has(file)) continue;
    if (!knownFiles.has(file)) throw new Error(`Missing dashboard entry: ${file}`);

    reachable.add(file);
    for (const target of importsByFile.get(file) || []) {
      if (!knownFiles.has(target)) {
        const importer = relative(packageRoot, file);
        const imported = relative(packageRoot, target);
        throw new Error(
          `Import target is not a dashboard JavaScript module in ${importer}: ${imported}`,
        );
      }
      pending.push(target);
    }
  }

  const unused = files.filter(file => !reachable.has(file));
  if (unused.length) {
    const unusedPaths = unused
      .map(file => relative(packageRoot, file))
      .join(", ");
    throw new Error(
      `Unreachable dashboard modules: ${unusedPaths}`,
    );
  }
}

function checkDomIds(htmlPath, sourceFiles) {
  const html = readFileSync(htmlPath, "utf8");
  const htmlIds = [...html.matchAll(/\bid=["']([^"']+)["']/g)].map(match => match[1]);
  const duplicateIds = htmlIds.filter((id, index) => htmlIds.indexOf(id) !== index);
  if (duplicateIds.length) {
    throw new Error(`Duplicate HTML ids: ${[...new Set(duplicateIds)].join(", ")}`);
  }

  const knownIds = new Set(htmlIds);
  const requiredIds = sourceFiles.flatMap(file => {
    const source = readFileSync(file, "utf8");
    return [...source.matchAll(/getElementById\(["']([^"']+)["']\)/g)]
      .map(match => match[1]);
  });
  const missingIds = requiredIds.filter(id => !knownIds.has(id));
  if (missingIds.length) {
    throw new Error(`Missing dashboard HTML ids: ${missingIds.join(", ")}`);
  }
}
