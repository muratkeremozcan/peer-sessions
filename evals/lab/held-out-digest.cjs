#!/usr/bin/env node
// Print the heldOutDigest TeA records in run.json for a held-out run of a view.
// Usage: node evals/lab/held-out-digest.cjs <view>
// It uses the installed TeA's own helpers, so the value matches what `run` and
// `check`'s held-out-drift warning compare.
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const lib = path.join(__dirname, '..', 'node_modules', 'bmad-method-test-architecture-enterprise', 'cli', 'lib', 'evaluate');
const { heldOutDigestOf } = require(path.join(lib, 'corpus-index'));
const { loadContractView } = require(path.join(lib, 'partition'));

async function main(folder) {
  const read = (name) => JSON.parse(fs.readFileSync(path.join(folder, name), 'utf8'));
  const evaluation = read('evaluation.json');
  const probes = fs
    .readdirSync(path.join(folder, 'probes'))
    .filter((name) => name.endsWith('.probe.json'))
    .sort()
    .map((name) => read(path.join('probes', name)));
  const digest = await heldOutDigestOf({
    index: read('corpus-index.json'),
    probes,
    heldOutProbes: evaluation.heldOutProbes,
    contract: loadContractView({ folder, evaluation, partition: 'held-out' }).contract,
  });
  process.stdout.write(`${digest}\n`);
}

if (process.argv.length !== 3) {
  process.stderr.write('usage: held-out-digest.cjs <view>\n');
  process.exit(64);
}
main(path.resolve(process.argv[2])).catch((error) => {
  process.stderr.write(`held-out-digest: ${error.message}\n`);
  process.exit(1);
});
