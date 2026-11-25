/**
 * LocalLens: keep legacy visible version strings in sync with frontend/package.json.
 * npm automatically runs this script before `npm run build` and `npm run dev`.
 * For new components, import APP_VERSION_LABEL from src/appVersion.js instead.
 */
import { readFileSync, writeFileSync, readdirSync, lstatSync } from 'node:fs';
import { dirname, join, resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(join(frontend, 'package.json'), 'utf8'));
if (!/^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$/.test(pkg.version || '')) {
  throw new Error('Invalid frontend/package.json version: expected semver.');
}
const version = pkg.version;
const versionParts = value => value.match(/^\d+\.\d+\.\d+/)[0].split('.').map(Number);
const compare = (a, b) => {
  const A = versionParts(a), B = versionParts(b);
  for (let i=0; i<3; i++) if (A[i]!==B[i]) return A[i]-B[i];
  return 0;
};
const label = `LocalLens v${version}`;
const literal = /LocalLens\s+v(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)/g;
const validExtensions = new Set(['.jsx', '.tsx', '.js', '.ts', '.html']);
let files = 0, labels = 0;
function visit(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const stat = lstatSync(path);
    if (stat.isSymbolicLink()) continue;
    if (stat.isDirectory()) { visit(path); continue; }
    if (!stat.isFile() || !validExtensions.has(extname(name))) continue;
    const original = readFileSync(path, 'utf8');
    let count = 0;
    const updated = original.replace(literal, (match, oldVersion) => {
      // Reject stale metadata rather than ever silently downgrading a displayed version.
      if (compare(oldVersion, version) > 0) {
        throw new Error(`${path} displays v${oldVersion} newer than package v${version}; bump package.json first.`);
      }
      count++;
      return label;
    });
    if (updated !== original) { writeFileSync(path, updated, 'utf8'); files++; }
    labels += count;
  }
}
visit(join(frontend, 'src'));
// Some installations render a visible version in index.html instead of JSX.
const htmlPath = join(frontend, 'index.html');
try {
  const html = readFileSync(htmlPath, 'utf8');
  const output = html.replace(literal, (match, oldVersion) => {
    if (compare(oldVersion, version) > 0) throw new Error('index.html contains a newer version than package.json.');
    labels++;
    return label;
  });
  if (output !== html) { writeFileSync(htmlPath, output, 'utf8'); files++; }
} catch (err) {
  if (err?.code !== 'ENOENT') throw err;
}
console.log(`[LocalLens] ${label}; synchronized ${labels} labels (${files} changed files).`);
