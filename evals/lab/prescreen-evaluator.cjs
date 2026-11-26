'use strict';

const fs = require('node:fs');
const { evaluateOracles } = require('bmad-method-test-architecture-enterprise/cli/lib/evaluate/evaluator');
const contract = require('../peer-sessions/contract.json');
const { regexMatchStepBudget } = require('../peer-sessions/policy/scoring-policy.json');

function capture(text) {
  try {
    return { kind: 'json', value: JSON.parse(text) };
  } catch {
    return { kind: 'text', value: text };
  }
}

async function main() {
  const { step, check, stdout } = JSON.parse(fs.readFileSync(0, 'utf8'));
  const oracleId = 'prescreen';
  const [result] = await evaluateOracles({
    contract: { ...contract, oracles: [{ id: oracleId, check, polarity: 'expects-hold' }] },
    stepObservations: { [step]: { observationId: oracleId, stdout: capture(stdout) } },
    oracleIds: [oracleId],
    regexMatchStepBudget,
  });
  console.log(result.resolution);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
