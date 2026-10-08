import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';

for (const file of process.argv.slice(2)) {
  const sample = JSON.parse(fs.readFileSync(file));
  const motions = Object.fromEntries(sample.motions.map(motion => [motion.name, motion]));
  const first = name => motions[name].frames[0];
  const last = name => motions[name].frames.at(-1);
  const equal = (left, right) => left.forEach((channel, index) => {
    assert.equal(channel[0], right[index][0]);
    assert(channel.every((value, component) => Math.abs(value - right[index][component]) < 1e-5), `endpoint joint ${index}`);
  });
  equal(first('lie_down'), first('idle'));
  equal(last('lie_down'), first('side_lying'));
  equal(last('side_lying'), first('get_up'));
  equal(last('get_up'), first('idle'));
  for (const name of ['lie_down', 'get_up', 'side_lying']) {
    const motion = motions[name];
    assert.equal(motion.frames.length, Math.ceil(motion.duration * 30) + 1);
    assert.equal(motion.looping, name === 'side_lying');
    for (const frame of motion.frames) {
      assert.equal(frame.length, sample.bones.length);
      assert(frame.every(channel => channel.length === 8 && channel.every(Number.isFinite)));
      assert(frame.every(channel => Math.abs(new THREE.Quaternion().fromArray(channel, 4).length() - 1) < 1e-4));
    }
    const bodyIndices = sample.bones.flatMap((bone, index) => /^(センター|下半身|上半身[12]?|首|頭|[左右](肩|腕|ひじ|手首|足|ひざ|足首))$/.test(bone.name) ? [index] : []);
    for (let frame = 1; frame < motion.frames.length; frame++) for (const index of bodyIndices) {
      assert(new THREE.Quaternion().fromArray(motion.frames[frame - 1][index], 4)
        .angleTo(new THREE.Quaternion().fromArray(motion.frames[frame][index], 4)) < 0.38, `${name} discontinuity ${sample.bones[index].name}`);
    }
  }
  assert.equal(sample.posture.model_sha256, sample.sha256);
  console.log('PASS:', file, 'whole-rig endpoints, finite channels, smooth body frames and matching provenance');
}
