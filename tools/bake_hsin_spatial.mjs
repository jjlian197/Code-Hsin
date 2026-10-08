import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {createBuiltinClips} from '../src/assets/pmx_viewer/motions.js';
import {createSpatialMesh} from './spatial_sampling.mjs';

const [modelPath, outputPath] = process.argv.slice(2);
if (!modelPath || !outputPath) throw new Error('Usage: bake_hsin_spatial.mjs model.pmx output.json');
const original = fs.readFileSync(modelPath);
const model = new Parser().parsePmx(original.buffer.slice(original.byteOffset, original.byteOffset + original.byteLength), true);
const heights = model.vertices.map(vertex => vertex.position[1]);
const scale = 1.65 / (Math.max(...heights) - Math.min(...heights));
const mesh = createSpatialMesh(model);
const bones = mesh.skeleton.bones;
const clips = createBuiltinClips(mesh);
const selectedNames = ['idle', 'wave', 'nod', 'peace', 'finger_heart', 'crossed_arms'];
const animatedNames = new Set(selectedNames.flatMap(name => clips[name].tracks.map(track => /\.bones\[(.*?)\]/.exec(track.name)?.[1]).filter(Boolean)));
const animatedIndices = bones.flatMap((bone, index) => animatedNames.has(bone.name) ? [index] : []);
const restPositions = bones.map(bone => bone.position.toArray());
const mixer = new THREE.AnimationMixer(mesh);
const motions = selectedNames.map(name => {
  mixer.stopAllAction();
  bones.forEach((bone, index) => { bone.position.fromArray(restPositions[index]); bone.quaternion.identity(); });
  // Desktop gestures are increments over the persistent lowered-arm idle layer.
  mixer.clipAction(clips.idle).reset().play();
  const clip = clips[name];
  if (name !== 'idle') mixer.clipAction(clip).reset().setLoop(THREE.LoopOnce, 1).play();
  const duration = name === 'idle' ? 6 : clip.duration;
  const frames = [];
  for (let frame = 0; frame <= Math.ceil(duration * 30); frame++) {
    mixer.setTime(Math.min(frame / 30, duration));
    frames.push(animatedIndices.map(index => [index, ...bones[index].position.toArray().map(value => value * scale), ...bones[index].quaternion.toArray()]));
  }
  return {name, duration, looping: name === 'idle', frames};
});
const payload = {
  source: path.resolve(modelPath), sha256: crypto.createHash('sha256').update(original).digest('hex'), scale,
  bones: model.bones.map((bone, index) => ({name: bone.name, parent: bone.parentIndex, position: restPositions[index].map(value => value * scale)})),
  vertices: model.vertices.map(vertex => ({position: vertex.position.map(value => value * scale), normal: vertex.normal,
    uv: [vertex.uv[0], 1 - vertex.uv[1]], joints: [...vertex.skinIndices, 0, 0, 0, 0].slice(0, 4), weights: [...vertex.skinWeights, 0, 0, 0, 0].slice(0, 4)})),
  faces: model.faces.map(face => face.indices), materials: model.materials, textures: model.textures,
  morphs: model.morphs.filter(morph => morph.type === 1).map(morph => ({name: morph.name,
    elements: morph.elements.map(element => ({index: element.index, offset: element.position.map(value => value * scale)}))})), motions
};
fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, JSON.stringify(payload));
console.log(JSON.stringify({vertices: payload.vertices.length, bones: bones.length, animatedBones: animatedIndices.length, motions: selectedNames}));
