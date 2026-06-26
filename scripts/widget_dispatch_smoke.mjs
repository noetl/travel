import Ajv from 'ajv';
import addFormats from 'ajv-formats';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
const envelope = JSON.parse(await readFile(path.join(root, 'playbooks/widget-contract/_envelope.schema.json'), 'utf8'));
const samples = JSON.parse(await readFile(path.join(root, 'src/contracts/sampleEnvelopes.json'), 'utf8'));
const validateEnvelope = ajv.compile(envelope);
const validators = new Map();
const schemaCache = new Map();
for (const sample of samples) {
  if (!schemaCache.has(sample.widget_type)) {
    const schema = JSON.parse(await readFile(path.join(root, 'playbooks/widget-contract', `${sample.widget_type}.schema.json`), 'utf8'));
    schemaCache.set(sample.widget_type, schema);
    ajv.addSchema(schema);
  }
}
for (const sample of samples) {
  if (!validators.has(sample.widget_type)) {
    validators.set(sample.widget_type, ajv.compile(schemaCache.get(sample.widget_type)));
  }
  if (!validateEnvelope(sample)) throw new Error(`Envelope failed for ${sample.widget_type}: ${ajv.errorsText(validateEnvelope.errors)}`);
  const validatePayload = validators.get(sample.widget_type);
  if (!validatePayload(sample.payload)) throw new Error(`Payload failed for ${sample.widget_type}: ${ajv.errorsText(validatePayload.errors)}`);
}
if (samples.length !== 26) throw new Error(`Expected 26 samples, got ${samples.length}`);
console.log(`Widget dispatch smoke passed for ${samples.length} widget envelopes`);
