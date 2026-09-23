'use strict';
const fs = require('fs');
const http = require('http');

let Main = 'main';
try { Main = require('n8n-workflow').NodeConnectionTypes.Main; } catch (_) {}

function request(method, path, body) {
  const base = new URL(process.env.LOCAL_OPENRPA_URL || 'http://127.0.0.1:8771');
  if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1') throw new Error('OpenRPA connection must be loopback HTTP');
  const tokenFile = process.env.LOCAL_OPENRPA_TOKEN_FILE;
  if (!tokenFile) throw new Error('本機 OpenRPA 連線未預先設定，請透過本機 Agent 啟動 n8n');
  const token = fs.readFileSync(tokenFile, 'utf8').trim();
  const payload = body === undefined ? undefined : JSON.stringify(body);
  return new Promise((resolve, reject) => {
    const req = http.request(new URL(path, base), {method, headers: {
      'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
      ...(payload ? {'Content-Length': Buffer.byteLength(payload)} : {}),
    }, timeout: 10000}, (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { text += chunk; if (text.length > 1000000) res.destroy(new Error('OpenRPA 回應過大')); });
      res.on('error', reject);
      res.on('end', () => {
        try {
          const data = JSON.parse(text);
          if (res.statusCode >= 400) reject(new Error(data.error || ('OpenRPA HTTP ' + res.statusCode)));
          else resolve(data);
        } catch (err) { reject(err); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('OpenRPA 本機橋接連線逾時')));
    req.on('error', reject);
    req.end(payload);
  });
}

class LocalOpenRpa {
  constructor() {
    this.description = {
      displayName: 'Local OpenRPA', name: 'localOpenRpa', group: ['transform'], version: 1,
      description: '透過預設本機 Port 執行已批准部署的 OpenRPA 流程',
      defaults: {name: 'Local OpenRPA', color: '#3669a8'}, inputs: [Main], outputs: [Main],
      properties: [
        {displayName: '操作', name: 'operation', type: 'options', default: 'run', options: [
          {name: '執行流程', value: 'run'}, {name: '查詢執行', value: 'status'}, {name: '取消執行', value: 'cancel'}]},
        {displayName: '部署 ID', name: 'deploymentId', type: 'string', default: '', required: true, displayOptions: {show: {operation: ['run']}}},
        {displayName: '輸入 JSON', name: 'input', type: 'json', default: '={{ $json }}', displayOptions: {show: {operation: ['run']}}},
        {displayName: '等待完成', name: 'waitForCompletion', type: 'boolean', default: true, displayOptions: {show: {operation: ['run']}}},
        {displayName: '執行 ID', name: 'runId', type: 'string', default: '', required: true, displayOptions: {show: {operation: ['status', 'cancel']}}},
      ],
    };
  }
  async execute() {
    const output = [];
    const items = this.getInputData();
    for (let i = 0; i < items.length; i++) {
      const operation = this.getNodeParameter('operation', i);
      let result;
      if (operation === 'run') {
        let input = this.getNodeParameter('input', i, {});
        if (typeof input === 'string') input = JSON.parse(input);
        if (!input || Array.isArray(input) || typeof input !== 'object') throw new Error('輸入必須為 JSON object');
        const executionId = this.getExecutionId();
        const runIndex = this.evaluateExpression('{{ $runIndex }}', i);
        if (!Number.isInteger(runIndex) || runIndex < 0) throw new Error('無法取得 n8n 執行索引');
        const key = [executionId, this.getNode().id, runIndex, i].join(':');
        result = await request('POST', '/v1/runs', {deployment_id: this.getNodeParameter('deploymentId', i), input, idempotency_key: key});
        if (this.getNodeParameter('waitForCompletion', i, true)) {
          const deadline = Date.now() + 220000;
          while (['queued', 'starting', 'running', 'cancel_requested'].includes(result.status)) {
            if (Date.now() > deadline) throw new Error('等待逾時，請查詢執行 ID：' + result.run_id + '；流程可能仍在執行');
            await new Promise(resolve => setTimeout(resolve, 500));
            result = await request('GET', '/v1/runs/' + encodeURIComponent(result.run_id));
          }
          if (result.status !== 'succeeded') throw new Error('OpenRPA ' + result.status + '：' + (result.error || '') + '；執行 ID：' + result.run_id);
        }
      } else {
        const run = String(this.getNodeParameter('runId', i));
        result = await request(operation === 'cancel' ? 'POST' : 'GET', '/v1/runs/' + encodeURIComponent(run) + (operation === 'cancel' ? '/cancel' : ''));
      }
      output.push({json: result, pairedItem: {item: i}});
    }
    return [output];
  }
}
module.exports = {LocalOpenRpa};
