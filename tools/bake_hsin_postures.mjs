import {spatialHsinIdentity} from './spatial_hsin_identity.mjs';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {MMDAnimationHelper} from '../src/assets/pmx_viewer/lib/three/addons/animation/MMDAnimationHelper.js';
import {transitionAssets} from '../src/assets/pmx_viewer/pose_transitions.js';
import {createBuiltinClips} from '../src/assets/pmx_viewer/motions.js';
import {PoseCloth} from '../src/assets/pmx_viewer/pose_cloth.js';
import {createSpatialMesh, boneChannels} from './spatial_sampling.mjs';

const [samplePath, transitionPath, outputPath] = process.argv.slice(2);
if (!outputPath) throw new Error('Usage: bake_hsin_postures.mjs sampled.json calibrated-transitions.json output.json');
const sample = JSON.parse(fs.readFileSync(samplePath));
const resolvedOutput = fs.existsSync(outputPath) ? fs.realpathSync(outputPath) : path.resolve(outputPath);
if ([samplePath, transitionPath, sample.source].some(input => fs.realpathSync(input) === resolvedOutput)) {
  throw new Error('Output must not overwrite original geometry, calibration or PMX');
}
const original = fs.readFileSync(sample.source);
const digest = crypto.createHash('sha256').update(original).digest('hex');
if (digest !== sample.sha256) throw new Error('Original PMX no longer matches geometry sample');
const model = new Parser().parsePmx(original.buffer.slice(original.byteOffset, original.byteOffset + original.byteLength), true);
const mesh = createSpatialMesh(model), bones = mesh.skeleton.bones;
const rest = bones.map(bone => ({position: bone.position.clone(), rotation: bone.quaternion.clone()}));
const transitions = transitionAssets(JSON.parse(fs.readFileSync(transitionPath)), spatialHsinIdentity(digest).calibrationHash, mesh);
const grantSolver = new MMDAnimationHelper().createGrantSolver(mesh);
const reset = () => bones.forEach((bone, index) => { bone.position.copy(rest[index].position); bone.quaternion.copy(rest[index].rotation); });
const update = () => {
  // PMX helper bones inherit animated joints; capture their evaluated transform for RealityKit.
  for (const grant of mesh.geometry.userData.MMD.grants) bones[grant.index].quaternion.identity();
  grantSolver.update(); mesh.updateMatrixWorld(true); mesh.skeleton.update();
};
const tracks = clip => clip.tracks.map(track => {
  const [, name, property] = track.name.match(/^\.bones\[(.+)\]\.(quaternion|position)$/);
  const bone = bones.find(candidate => candidate.name === name);
  if (!bone) throw new Error('Missing posture joint: ' + name);
  return {bone, property, interpolant: track.createInterpolant()};
});
const apply = (channels, seconds) => channels.forEach(channel => channel.bone[channel.property].fromArray(channel.interpolant.evaluate(seconds)));
const idle = tracks(createBuiltinClips(mesh).idle);
// Every clip restores the whole rig, including center translation and garment helpers.
// Otherwise returning to an upper-body idle leaves the lying root/legs behind.
for (const motion of sample.motions) {
  motion.frames = motion.frames.map(frame => {
    reset();
    for (const channel of frame) {
      bones[channel[0]].position.fromArray(channel.slice(1, 4).map(value => value / sample.scale));
      bones[channel[0]].quaternion.fromArray(channel.slice(4));
    }
    update(); return boneChannels(mesh, sample.scale);
  });
}
const standing = sample.motions.find(motion => motion.name === 'idle').frames[0];
const cloth = new PoseCloth(mesh, transitions.floor);
const realtimeCloth = process.argv.includes('--realtime-cloth');
const feet = ['左', '右'].map(side => ({
  ankle: bones.find(bone => bone.name === side + '足首'),
  knee: bones.find(bone => bone.name === side + 'ひざ'),
}));
const alignFootDorsum = strength => {
  mesh.updateMatrixWorld(true);
  for (const {ankle, knee} of feet) {
    // Derive a foot frame from the actual shin, keeping toes along the leg and
    // the dorsum toward the window front (+Z), instead of imposing a world yaw.
    const toe = ankle.getWorldPosition(new THREE.Vector3()).sub(knee.getWorldPosition(new THREE.Vector3())).normalize();
    const dorsal = new THREE.Vector3(0, 0, 1).addScaledVector(toe, -toe.z).normalize();
    const across = new THREE.Vector3().crossVectors(dorsal, toe).normalize();
    const world = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(across, dorsal, toe));
    const local = ankle.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(world);
    ankle.quaternion.slerp(local, strength).normalize();
  }
};
const evaluate = (channels, seconds, strength = 1, feetStrength = 1) => {
  reset(); apply(idle, seconds); apply(channels, seconds);
  if (feetStrength > 0) alignFootDorsum(feetStrength);
  update();
  if (!realtimeCloth) cloth.update(1 / 30, strength); mesh.updateMatrixWorld(true); mesh.skeleton.update();
};
const side = tracks(transitions.clips.side_lying);
// A deterministic settled hold lets both independently baked transitions meet exactly.
cloth.stop();
for (let index = 0; index < 120; index++) evaluate(side, 0);
const lying = boneChannels(mesh, sample.scale);
const blend = (frame, endpoint, weight) => frame.map((channel, index) => {
  const position = new THREE.Vector3().fromArray(channel, 1).lerp(new THREE.Vector3().fromArray(endpoint[index], 1), weight);
  const rotation = new THREE.Quaternion().fromArray(channel, 4).slerp(new THREE.Quaternion().fromArray(endpoint[index], 4), weight);
  return [index, ...position.toArray(), ...rotation.toArray()];
});
const envelope = new THREE.Box3(), point = new THREE.Vector3();
const applyFrame = frame => {
  reset();
  for (const channel of frame) {
    bones[channel[0]].position.fromArray(channel.slice(1, 4).map(value => value / sample.scale));
    bones[channel[0]].quaternion.fromArray(channel.slice(4));
  }
  mesh.updateMatrixWorld(true); mesh.skeleton.update();
};
for (const [name, clip] of Object.entries(transitions.clips)) {
  const channels = tracks(clip), frames = [];
  cloth.stop();
  const initial = name === 'get_up' || name === 'side_lying' ? lying : standing;
  const final = name === 'get_up' ? standing : lying;
  for (let index = 0; index <= Math.ceil(clip.duration * 30); index++) {
    const seconds = Math.min(index / 30, clip.duration);
    const feetStrength = name === 'side_lying' ? 1 : name === 'lie_down'
      ? THREE.MathUtils.smoothstep(seconds, 2.5, 6)
      : 1 - THREE.MathUtils.smoothstep(seconds, 1, 4);
    evaluate(channels, seconds, name === 'get_up' ? THREE.MathUtils.smoothstep(clip.duration - seconds, 0, 0.6) : 1, feetStrength);
    let frame = name === 'side_lying' ? structuredClone(lying) : boneChannels(mesh, sample.scale);
    // Preserve a whole-rig handoff, including offline garment motion; no frozen-pose snap.
    if (name !== 'side_lying') {
      frame = blend(frame, initial, 1 - THREE.MathUtils.smoothstep(seconds, 0, 0.35));
      frame = blend(frame, final, THREE.MathUtils.smoothstep(seconds, clip.duration - 0.6, clip.duration));
    }
    frames.push(frame);
    if (index % 15 === 0 || seconds === clip.duration) {
      applyFrame(frame);
      for (let vertex = 0; vertex < model.vertices.length; vertex++) envelope.expandByPoint(mesh.getVertexPosition(vertex, point).multiplyScalar(sample.scale));
    }
  }
  sample.motions.push({name, duration: clip.duration, looping: name === 'side_lying', frames});
}
sample.realtime_cloth = realtimeCloth;
sample.posture = {source_sha256: crypto.createHash('sha256').update(fs.readFileSync(transitionPath)).digest('hex'),
  model_sha256: digest, floor: transitions.floor * sample.scale,
  feet: 'Shin-aligned toes; dorsum toward window front (+Z), blended through transitions',
  bounds: {min: envelope.min.toArray(), max: envelope.max.toArray()},
  cloth: 'Desktop PoseCloth sampled offline; settled side hold',
  limitations: ['No real-time cloth or per-vertex desktop ground projection; frozen settled hold']};
fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, JSON.stringify(sample));
console.log(JSON.stringify({motions: sample.motions.map(motion => motion.name), posture: sample.posture}));
