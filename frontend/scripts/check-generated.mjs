import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const temporary = mkdtempSync(path.join(tmpdir(), 'meridian-contract-'));
try {
  const output = path.join(temporary, 'api.ts');
  execFileSync(process.execPath, ['node_modules/openapi-typescript/bin/cli.js', '../contracts/openapi.json', '-o', output], {stdio:'pipe'});
  if (readFileSync(output, 'utf8') !== readFileSync('generated/api.ts', 'utf8')) {
    console.error('Generated API types drifted: run npm run generate'); process.exitCode = 1;
  } else console.log('Generated TypeScript contract is current.');
} finally { rmSync(temporary, {recursive:true}); }
