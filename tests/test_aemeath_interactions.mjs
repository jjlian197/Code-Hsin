import fs from 'node:fs';
import assert from 'node:assert/strict';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
const sample = JSON.parse(fs.readFileSync(process.argv[2]));
const motions = Object.fromEntries(sample.motions.map(motion => [motion.name, motion]));
const ids = motions.idle.frames[0].map(channel => channel[0]);
const equal = (left, right) => assert(left.every((channel, index) => channel.every((value, axis) => Math.abs(value - right[index][axis]) < 1e-5)));
for (const motion of sample.motions) {
  for (const frame of motion.frames) {
    assert.deepEqual(frame.map(channel => channel[0]), ids);
    assert(frame.flat().every(Number.isFinite));
    assert(frame.every(channel => Math.abs(Math.hypot(...channel.slice(4)) - 1) < 1e-4));
  }
  assert.equal(sample.behavior.touchFrames[motion.name].length, motion.frames.length);
}
equal(motions.lie_down.frames[0], motions.idle.frames[0]);
equal(motions.lie_down.frames.at(-1), motions.side_lying.frames[0]);
equal(motions.get_up.frames[0], motions.side_lying.frames.at(-1));
equal(motions.get_up.frames.at(-1), motions.idle.frames[0]);
equal(motions.treadmill_running.frames[0], motions.idle.frames[0]);
equal(motions.treadmill_running.frames.at(-1), motions.idle.frames[0]);
let maximum = 0;
for (const name of ['lie_down', 'get_up', 'side_lying']) {
  for (let index = 1; index < motions[name].frames.length; index++) {
    for (let joint = 0; joint < ids.length; joint++) {
      const angle = new THREE.Quaternion().fromArray(motions[name].frames[index - 1][joint], 4).angleTo(new THREE.Quaternion().fromArray(motions[name].frames[index][joint], 4));
      maximum = Math.max(maximum, angle);
      assert(angle < 0.6, `${name} joint ${ids[joint]} jump ${angle}`);
    }
  }
}
assert.equal(Object.keys(sample.behavior.expressions).length, 12);
assert.equal(sample.behavior.touchRegions.length, 5);
console.log(`Aemeath ${sample.motions.length} clips, ${ids.length} common animated joints, endpoints, finite data and continuity passed; largest step ${maximum}`);
