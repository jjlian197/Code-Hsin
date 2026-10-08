import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {spatialHsinIdentity} from '../tools/spatial_hsin_identity.mjs';
assert.throws(() => spatialHsinIdentity('0'.repeat(64)), /Uncalibrated/);
for (const path of process.argv.slice(2)) {
  const sample = JSON.parse(fs.readFileSync(path)), identity = spatialHsinIdentity(sample.sha256);
  assert(identity.trial && sample.realtime_cloth && sample.trial_chest_rig);
  const bytes = fs.readFileSync(sample.source);
  assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), sample.sha256);
  const model = new Parser().parsePmx(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), true);
  const auxiliaries = model.bones.filter(bone => /^ZSpring_Spine_/.test(bone.name));
  assert.equal(auxiliaries.length, 10);
  for (const bone of auxiliaries) {
    assert(bone.flag & 0x1000);
    assert.equal(model.bones[bone.parentIndex].name, bone.name.endsWith('_L') ? '左胸' : '右胸');
  }
  assert.equal(sample.physics.postGrants.length, 10);
  const simulated = new Set(sample.physics.nodes.map(node => sample.physics.joints[node.joint].bone));
  assert(!simulated.has('左胸') && !simulated.has('右胸'));
  assert(!simulated.has('センター') && !simulated.has('上半身'));
  console.log(`${identity.form}: trial hash, ten post-physics parents/grants and body isolation passed`);
}
