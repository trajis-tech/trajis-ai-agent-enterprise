const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {LocalOpenRpa} = require('../app/integrations/n8n/LocalOpenRpa.node.js');
(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rpa-node-test-'));
  const token = path.join(dir, 'token.txt');
  fs.writeFileSync(token, 'test-only-token');
  const keys = [];
  const server = http.createServer((req, res) => {
    assert.equal(req.headers.authorization, 'Bearer test-only-token');
    let body = '';
    req.on('data', data => body += data);
    req.on('end', () => {
      keys.push(JSON.parse(body).idempotency_key);
      res.writeHead(202, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({run_id: 'test', status: 'queued'}));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  process.env.LOCAL_OPENRPA_URL = `http://127.0.0.1:${server.address().port}`;
  process.env.LOCAL_OPENRPA_TOKEN_FILE = token;
  try {
    let runIndex = 0;
    const context = {
      getInputData: () => [{json: {}}], getExecutionId: () => 'execution',
      getNode: () => ({id: 'node'}),
      evaluateExpression: expression => { assert.equal(expression, '{{ $runIndex }}'); return runIndex; },
      getNodeParameter: name => ({operation: 'run', input: {}, deploymentId: 'test', waitForCompletion: false})[name],
    };
    await LocalOpenRpa.prototype.execute.call(context);
    await LocalOpenRpa.prototype.execute.call(context);
    runIndex++;
    await LocalOpenRpa.prototype.execute.call(context);
    assert.equal(keys[0], keys[1], 'same iteration retries are idempotent');
    assert.notEqual(keys[0], keys[2], 'next loop iteration must execute');
    console.log('OpenRPA node loop/retry/auth checks passed');
  } finally {
    await new Promise(resolve => server.close(resolve));
    fs.unlinkSync(token); fs.rmdirSync(dir);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
