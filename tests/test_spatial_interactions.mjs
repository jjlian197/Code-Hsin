import fs from 'node:fs';
import assert from 'node:assert/strict';

for (const source of process.argv.slice(2)) {
  const sample = JSON.parse(fs.readFileSync(source));
  const standing = sample.motions.find(motion => motion.name === 'idle').frames[0];
  const running = sample.motions.find(motion => motion.name === 'treadmill_running');
  const breathing = sample.motions.find(motion => motion.name === 'idle_breathing');
  assert(Math.abs(running.duration - 15.733333587646484) < 1e-5);
  assert(!running.looping && breathing.looping);
  for (const motion of [running, breathing]) {
    for (const frame of motion.frames) {
      assert.equal(frame.length, sample.bones.length);
      for (const channel of frame) {
        assert(channel.every(Number.isFinite));
        assert(Math.abs(Math.hypot(...channel.slice(4)) - 1) < 1e-5);
      }
    }
    for (const index of [0, motion.frames.length - 1]) {
      for (let joint = 0; joint < standing.length; joint++) {
        for (let value = 1; value < 8; value++) assert(Math.abs(motion.frames[index][joint][value] - standing[joint][value]) < 1e-5);
      }
    }
  }
  assert(breathing.frames.some(frame => frame.some((channel, joint) => Math.abs(channel[4] - standing[joint][4]) > 0.001)));
  assert.equal(sample.behavior.touchRegions.length, 5);
  for (const motion of sample.motions) {
    const frames = sample.behavior.touchFrames[motion.name];
    assert.equal(frames.length, motion.frames.length);
    for (const frame of frames) {
      assert.equal(frame.length, 5);
      assert(frame.flat().every(Number.isFinite));
    }
  }
  const headIndex = sample.behavior.touchRegions.findIndex(region => region.name === 'head');
  const sideHead = sample.behavior.touchFrames.side_lying[0][headIndex];
  const standingHead = sample.behavior.touchFrames.idle[0][headIndex];
  assert(Math.hypot(...sideHead.map((value, axis) => value - standingHead[axis])) > 0.3);
  console.log(source + ': running/breathing endpoints, whole rig and pose-following touch samples passed');
}
