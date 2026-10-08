import {spatialClothConfig} from './spatial_cloth_config.mjs';
import {spatialHsinIdentity} from './spatial_hsin_identity.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {MMDAnimationHelper} from '../src/assets/pmx_viewer/lib/three/addons/animation/MMDAnimationHelper.js';
import {runningClip} from '../src/assets/pmx_viewer/hsin_motion.js';
import {expressions} from '../src/assets/pmx_viewer/behavior.js';
import {createSpatialMesh, boneChannels} from './spatial_sampling.mjs';

const [inputPath, outputPath] = process.argv.slice(2);
if (!outputPath) throw new Error('Usage: bake_hsin_interactions.mjs posture-sample.json output.json');
const sample = JSON.parse(fs.readFileSync(inputPath));
const output = fs.existsSync(outputPath) ? fs.realpathSync(outputPath) : path.resolve(outputPath);
if ([inputPath, sample.source].some(source => fs.realpathSync(source) === output)) throw new Error('Output must not replace source assets');
const original = fs.readFileSync(sample.source);
const digest = crypto.createHash('sha256').update(original).digest('hex');
const form = spatialHsinIdentity(digest).form;
if (!form || digest !== sample.sha256) throw new Error('Uncalibrated or changed PMX');
const model = new Parser().parsePmx(original.buffer.slice(original.byteOffset, original.byteOffset + original.byteLength), true);
const mesh = createSpatialMesh(model), bones = mesh.skeleton.bones;
const grant = new MMDAnimationHelper().createGrantSolver(mesh);
const idle = sample.motions.find(motion => motion.name === 'idle');
const standing = idle.frames[0];
const applyFrame = frame => {
  for (const channel of frame) {
    bones[channel[0]].position.fromArray(channel.slice(1, 4).map(value => value / sample.scale));
    bones[channel[0]].quaternion.fromArray(channel.slice(4));
  }
};
const update = () => {
  for (const source of mesh.geometry.userData.MMD.grants) bones[source.index].quaternion.identity();
  grant.update(); mesh.updateMatrixWorld(true); mesh.skeleton.update();
};
const breathing = [];
for (let index = 0; index <= 282; index++) {
  applyFrame(standing);
  const breath = Math.sin(index / 30 * Math.PI * 2 / 4.7);
  for (const [name, angle] of [['上半身', 0.009], ['上半身2', 0.008]]) {
    const bone = bones.find(candidate => candidate.name === name);
    if (bone) bone.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), breath * angle));
  }
  const torso = bones.find(bone => bone.name === '上半身');
  if (torso) torso.position.y += breath * 0.05;
  update(); breathing.push(boneChannels(mesh, sample.scale));
}
sample.motions.push({name: 'idle_breathing', duration: 9.4, looping: true, frames: breathing});
const calibrationPath = path.resolve('src/assets/motions/running-' + form + '.json');
const calibrationBytes = fs.readFileSync(calibrationPath);
const clip = runningClip(JSON.parse(calibrationBytes), mesh);
const channels = clip.tracks.map(track => {
  const [, name, property] = track.name.match(/^\.bones\[(.+)\]\.(quaternion|position)$/);
  return {bone: bones.find(bone => bone.name === name), property, interpolant: track.createInterpolant()};
});
const running = [];
for (let index = 0; index <= Math.ceil(clip.duration * 30); index++) {
  const seconds = Math.min(index / 30, clip.duration);
  applyFrame(standing);
  for (const channel of channels) channel.bone[channel.property].fromArray(channel.interpolant.evaluate(seconds));
  // Fit both ends to the complete standing rig. Desktop's abrupt finish cannot be copied to a spatial character.
  const strength = THREE.MathUtils.smoothstep(seconds, 0, 0.45) * THREE.MathUtils.smoothstep(clip.duration - seconds, 0, 0.6);
  bones.forEach((bone, joint) => {
    bone.position.lerp(new THREE.Vector3().fromArray(standing[joint], 1).multiplyScalar(1 / sample.scale), 1 - strength);
    bone.quaternion.slerp(new THREE.Quaternion().fromArray(standing[joint], 4), 1 - strength);
  });
  update(); running.push(boneChannels(mesh, sample.scale));
}
sample.motions.push({name: 'treadmill_running', duration: clip.duration, looping: false, frames: running});
const regions = [
  {name: 'head', bone: '頭', radius: 0.10},
  {name: 'left_hand', bone: '左手首', radius: 0.065},
  {name: 'right_hand', bone: '右手首', radius: 0.065},
  {name: 'chest', bone: '上半身2', radius: 0.12},
  {name: 'body', bone: '下半身', radius: 0.14},
].filter(region => bones.some(bone => bone.name === region.bone));
const touchFrames = {};
const envelope = new THREE.Box3(new THREE.Vector3().fromArray(sample.posture.bounds.min), new THREE.Vector3().fromArray(sample.posture.bounds.max));
const point = new THREE.Vector3();
for (const motion of sample.motions) {
  // Follow sampled current bones instead of reusing standing-screen hit rectangles in a lying pose.
  touchFrames[motion.name] = motion.frames.map((frame, index) => {
    applyFrame(frame); mesh.updateMatrixWorld(true); mesh.skeleton.update();
    if (motion.name === 'treadmill_running' && (index % 15 === 0 || index === motion.frames.length - 1)) {
      for (let vertex = 0; vertex < model.vertices.length; vertex++) envelope.expandByPoint(mesh.getVertexPosition(vertex, point).multiplyScalar(sample.scale));
    }
    return regions.map(region => bones.find(bone => bone.name === region.bone).getWorldPosition(new THREE.Vector3()).multiplyScalar(sample.scale).toArray());
  });
}
sample.posture.bounds = {min: envelope.min.toArray(), max: envelope.max.toArray()};
sample.behavior = {expressions, touchRegions: regions.map(({name, radius}) => ({name, radius})), touchFrames,
  running_calibration_sha256: crypto.createHash('sha256').update(calibrationBytes).digest('hex'),
  limitations: ['Touch uses animated bone spheres, not exact skinned-triangle raycasts', 'Running has no real-time garment physics']};
if (sample.realtime_cloth) {
  const dynamic = model.rigidBodies.filter(body => body.type > 0 && body.boneIndex >= 0).map(body => body.boneIndex);
  const seams = model.constraints.map(link => [model.rigidBodies[link.rigidBodyIndex1]?.boneIndex, model.rigidBodies[link.rigidBodyIndex2]?.boneIndex]);
  const grants = model.bones.flatMap((bone, index) => /^ZSpring_Spine_/.test(bone.name) && bone.grant ? [{joint: index, source: bone.grant.parentIndex, ratio: bone.grant.ratio}] : []);
  sample.physics = spatialClothConfig(sample.bones, sample.bones.map((_, index) => index), dynamic, seams, sample.posture.floor, digest, grants);
  sample.posture.cloth = 'Neutral garment animation; native realtime bone PBD';
  sample.posture.limitations = ['Native bone constraints do not provide per-vertex or self collision'];
}
fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, JSON.stringify(sample));
console.log(JSON.stringify({form, motions: sample.motions.map(motion => motion.name), touchRegions: regions.length}));
