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
  if (sample.posture.feet) {
    const frame = first('side_lying'), worlds = [];
    const world = index => {
      if (worlds[index]) return worlds[index];
      const channel = frame[index];
      const local = new THREE.Matrix4().compose(new THREE.Vector3().fromArray(channel, 1),
        new THREE.Quaternion().fromArray(channel, 4), new THREE.Vector3(1, 1, 1));
      const parent = sample.bones[index].parent;
      return worlds[index] = parent < 0 ? local : world(parent).clone().multiply(local);
    };
    for (const side of ['左', '右']) {
      const ankle = sample.bones.findIndex(bone => bone.name === side + '足首');
      const knee = sample.bones.findIndex(bone => bone.name === side + 'ひざ');
      const rotation = new THREE.Quaternion().setFromRotationMatrix(world(ankle));
      const dorsal = new THREE.Vector3(0, 1, 0).applyQuaternion(rotation);
      const toe = new THREE.Vector3(0, 0, 1).applyQuaternion(rotation);
      const shin = new THREE.Vector3().setFromMatrixPosition(world(ankle))
        .sub(new THREE.Vector3().setFromMatrixPosition(world(knee))).normalize();
      assert(dorsal.z > .97, `${side} foot dorsum must face window front`);
      assert(toe.dot(shin) > .99, `${side} toes must follow shin direction`);
    }
  }
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
