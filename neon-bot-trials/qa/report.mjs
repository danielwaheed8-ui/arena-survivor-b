/**
 * Turns the Playwright JSON results into qa/artifacts/REPORT.md so the visual
 * QA outcome (and every captured screenshot) can be reviewed at a glance.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const artifacts = path.join(dir, 'artifacts');
const resultsPath = path.join(artifacts, 'results.json');

if (!fs.existsSync(resultsPath)) {
  console.error('No results.json found — run `npm run visual:qa` first.');
  process.exit(1);
}

const results = JSON.parse(fs.readFileSync(resultsPath, 'utf8'));

const rows = [];
let passed = 0;
let failed = 0;

function walk(suite, chain = []) {
  for (const child of suite.suites ?? []) walk(child, [...chain, child.title]);
  for (const spec of suite.specs ?? []) {
    for (const t of spec.tests ?? []) {
      const project = t.projectName ?? t.projectId ?? '';
      const ok = t.results?.every((r) => r.status === 'passed' || r.status === 'skipped');
      if (ok) passed += 1;
      else failed += 1;
      rows.push(
        `| ${ok ? '✅' : '❌'} | ${chain.filter(Boolean).join(' › ')} › ${spec.title} | ${project} |`,
      );
    }
  }
}
for (const suite of results.suites ?? []) walk(suite, [suite.title]);

const screenshots = fs
  .readdirSync(artifacts)
  .filter((f) => f.endsWith('.png'))
  .sort();

const md = `# Neon Bot Trials — Visual QA Report

Generated: ${new Date().toISOString()}
Result: **${failed === 0 ? 'PASS' : 'FAIL'}** — ${passed} passed, ${failed} failed.

## Checks

| Status | Test | Viewport |
| --- | --- | --- |
${rows.join('\n')}

## Screenshot artifacts

${screenshots.map((s) => `- \`qa/artifacts/${s}\``).join('\n')}
`;

fs.writeFileSync(path.join(artifacts, 'REPORT.md'), md);
console.log(`\nVisual QA: ${failed === 0 ? 'PASS' : 'FAIL'} (${passed} passed, ${failed} failed)`);
console.log(`Report: qa/artifacts/REPORT.md, ${screenshots.length} screenshots captured.`);
process.exit(failed === 0 ? 0 : 1);
