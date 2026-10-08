// Retarget calibrated body poses in world space; Aemeath's local GLB axes differ from PMX.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';

const [modelPath, desktopPath, sourcePath, outputPath] = process.argv.slice(2);
if (!outputPath) throw new Error('Usage: bake_aemeath_interactions.mjs aemeath.glb desktop.json hsin-interactions.json output.json');
const raw = fs.readFileSync(modelPath);
const digest = crypto.createHash('sha256').update(raw).digest('hex');
if (digest !== '9fad847916728e0b293c78998173fb96ad3fd00ed66ea923a3886acd032420ed') throw new Error('Uncalibrated Aemeath GLB');
const destination = fs.existsSync(outputPath) ? fs.realpathSync(outputPath) : path.resolve(outputPath);
if ([modelPath, desktopPath, sourcePath].some(source => fs.realpathSync(source) === destination)) throw new Error('Output cannot overwrite source');
const model = JSON.parse(raw.toString('utf8', 20, 20 + raw.readUInt32LE(12)));
const binary = raw.subarray(28 + raw.readUInt32LE(12));
const desktop = JSON.parse(fs.readFileSync(desktopPath));
const source = JSON.parse(fs.readFileSync(sourcePath));
if (source.sha256 !== '4cf8454f7a79c84b88cf3dadfaca3fe2d55d3c6349fffd204acaf24dc78ea82e') throw new Error('Uncalibrated source pose');
const makeRig = definitions => {
  const nodes = definitions.map(definition => {
    const bone = new THREE.Object3D(); bone.name = definition.name ?? '';
    bone.position.fromArray(definition.translation ?? definition.position ?? [0, 0, 0]);
    bone.quaternion.fromArray(definition.rotation ?? [0, 0, 0, 1]);
    bone.scale.fromArray(definition.scale ?? [1, 1, 1]);
    return bone;
  });
  const root = new THREE.Object3D();
  definitions.forEach((definition, index) => {
    if (definition.parent >= 0) nodes[definition.parent].add(nodes[index]); else root.add(nodes[index]);
  });
  root.updateMatrixWorld(true);
  return {nodes, root, names: new Map(nodes.map((bone, index) => [bone.name, index]))};
};
const parents = new Map(model.nodes.flatMap((node, index) => (node.children ?? []).map(child => [child, index])));
const target = makeRig(model.nodes.map((node, index) => ({...node, parent: parents.get(index) ?? -1})));
const origin = makeRig(source.bones);
const channel = rig => rig.nodes.map((bone, index) => [index, ...bone.position.toArray(), ...bone.quaternion.toArray()]);
const apply = (rig, frame) => {
  frame.forEach(values => { rig.nodes[values[0]].position.fromArray(values, 1); rig.nodes[values[0]].quaternion.fromArray(values, 4); });
  rig.root.updateMatrixWorld(true);
};
const targetRest = channel(target);
const idlePartial = desktop.motions.find(motion => motion.name === 'idle').frames[0];
apply(target, idlePartial);
const targetIdle = channel(target);
const sourceIdle = source.motions.find(motion => motion.name === 'idle').frames[0];
apply(origin, sourceIdle);
const originalWorld = origin.nodes.map(bone => bone.getWorldQuaternion(new THREE.Quaternion()));
const targetWorld = target.nodes.map(bone => bone.getWorldQuaternion(new THREE.Quaternion()));
const worldPosition = (rig, name) => rig.nodes[rig.names.get(name)].getWorldPosition(new THREE.Vector3());
const heightRatio = worldPosition(target, '頭').y / worldPosition(origin, '頭').y;
const mapping = new Map();
const central = ['全ての親', 'センター', 'グルーブ', '腰', '下半身', '上半身', '上半身2', '首', '頭'];
for (const name of central) if (target.names.has(name) && origin.names.has(name)) mapping.set(target.names.get(name), origin.names.get(name));
for (const [suffix, prefix] of [['.L', '左'], ['.R', '右']]) {
  for (const name of ['肩', '腕', 'ひじ', '手首', '足', 'ひざ', '足首', 'つま先']) {
    if (target.names.has(name + suffix) && origin.names.has(prefix + name)) mapping.set(target.names.get(name + suffix), origin.names.get(prefix + name));
  }
  for (const [name, targetIndex] of target.names) {
    if (name.endsWith(suffix) && /指/.test(name)) {
      const original = origin.names.get(prefix + name.slice(0, -2));
      if (original !== undefined) mapping.set(targetIndex, original);
    }
  }
}
const ordered = [];
const visit = bone => { if (bone !== target.root) ordered.push(target.nodes.indexOf(bone)); bone.children.forEach(visit); };
visit(target.root);
const blend = (frame, pose, weight) => frame.map((values, index) => [index,
  ...new THREE.Vector3().fromArray(values, 1).lerp(new THREE.Vector3().fromArray(pose[index], 1), weight).toArray(),
  ...new THREE.Quaternion().fromArray(values, 4).slerp(new THREE.Quaternion().fromArray(pose[index], 4), weight).toArray()]);
const names = {heart: 'finger_heart', cross: 'crossed_arms', idle: 'idle_breathing'};
const motions = desktop.motions.map(motion => {
  const frames = motion.frames.map((frame, index) => {
    apply(target, targetIdle); apply(target, frame);
    let completed = channel(target);
    if (!motion.looping) {
      const seconds = index / 30;
      completed = blend(completed, targetIdle, 1 - THREE.MathUtils.smoothstep(seconds, 0, .3));
      completed = blend(completed, targetIdle, THREE.MathUtils.smoothstep(seconds, motion.duration - .35, motion.duration));
    }
    return completed;
  });
  return {...motion, name: names[motion.name] ?? motion.name, frames};
});
motions.push({name: 'idle', duration: 6, looping: true, frames: Array.from({length: 181}, () => structuredClone(targetIdle))});
const setWorldRotation = (bone, desired) => {
  bone.quaternion.copy(bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(desired));
  target.root.updateMatrixWorld(true);
};
const aimArm = (suffix, goal, strength) => {
  const wrist = target.nodes[target.names.get('手首' + suffix)];
  const destination = wrist.getWorldPosition(new THREE.Vector3()).lerp(goal, strength);
  // CCD uses the target bone lengths and parent world frames, never PMX local angles.
  for (let iteration = 0; iteration < 8; iteration++) {
    for (const name of ['ひじ', '腕', '肩']) {
      const bone = target.nodes[target.names.get(name + suffix)];
      const pivot = bone.getWorldPosition(new THREE.Vector3());
      const current = wrist.getWorldPosition(new THREE.Vector3()).sub(pivot);
      const desired = destination.clone().sub(pivot);
      if (current.lengthSq() > 1e-8 && desired.lengthSq() > 1e-8) {
        const delta = new THREE.Quaternion().setFromUnitVectors(current.normalize(), desired.normalize());
        setWorldRotation(bone, delta.multiply(bone.getWorldQuaternion(new THREE.Quaternion())));
      }
    }
  }
};
const palmFrame = (rig, wristName, middleName, indexName, littleName) => {
  const up = worldPosition(rig, middleName).sub(worldPosition(rig, wristName)).normalize();
  const across = worldPosition(rig, indexName).sub(worldPosition(rig, littleName)).normalize();
  const normal = new THREE.Vector3().crossVectors(across, up).normalize();
  const side = new THREE.Vector3().crossVectors(up, normal).normalize();
  return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(side, up, normal));
};
const retarget = (sourceFrame, support) => {
  apply(origin, sourceFrame); apply(target, targetIdle);
  for (const targetIndex of ordered) {
    const originalIndex = mapping.get(targetIndex);
    if (originalIndex === undefined) continue;
    const bone = target.nodes[targetIndex], originalBone = origin.nodes[originalIndex];
    const desired = originalBone.getWorldQuaternion(new THREE.Quaternion()).multiply(originalWorld[originalIndex].clone().invert()).multiply(targetWorld[targetIndex]);
    setWorldRotation(bone, desired);
    const displacement = originalBone.position.clone().sub(new THREE.Vector3().fromArray(sourceIdle[originalIndex], 1));
    const originalParent = source.bones[originalIndex].parent;
    if (originalParent >= 0) displacement.applyQuaternion(originalWorld[originalParent]);
    const targetParent = parents.get(targetIndex);
    if (targetParent !== undefined) displacement.applyQuaternion(targetWorld[targetParent].clone().invert());
    bone.position.fromArray(targetIdle[targetIndex], 1).add(displacement.multiplyScalar(heightRatio));
    target.root.updateMatrixWorld(true);
  }
  if (support > 0) {
    for (const [suffix, prefix] of [['.L', '左'], ['.R', '右']]) {
      const goal = worldPosition(origin, prefix + '手首').sub(worldPosition(origin, '頭')).multiplyScalar(heightRatio).add(worldPosition(target, '頭'));
      aimArm(suffix, goal, support);
      const wrist = target.nodes[target.names.get('手首' + suffix)];
      const desiredFrame = palmFrame(origin, prefix + '手首', prefix + '中指２', prefix + '人指１', prefix + '小指１');
      const currentFrame = palmFrame(target, '手首' + suffix, '中指２' + suffix, '人指１' + suffix, '小指１' + suffix);
      const correction = new THREE.Quaternion().slerp(desiredFrame.multiply(currentFrame.invert()), support);
      setWorldRotation(wrist, correction.multiply(wrist.getWorldQuaternion(new THREE.Quaternion())));
    }
  }
  return channel(target);
};
let lying;
for (const name of ['side_lying', 'lie_down', 'get_up', 'treadmill_running']) {
  const motion = source.motions.find(candidate => candidate.name === name);
  const frames = motion.frames.map((frame, index) => {
    const seconds = index / 30;
    const support = name === 'side_lying' ? 1 : name === 'lie_down' ? THREE.MathUtils.smoothstep(seconds, 2.5, 6) : name === 'get_up' ? 1 - THREE.MathUtils.smoothstep(seconds, 1, 4) : 0;
    let captured = retarget(frame, support);
    if (name === 'side_lying') return captured;
    const beginning = name === 'get_up' ? lying : targetIdle;
    const ending = name === 'lie_down' ? lying : targetIdle;
    captured = blend(captured, beginning, 1 - THREE.MathUtils.smoothstep(seconds, 0, .35));
    return blend(captured, ending, THREE.MathUtils.smoothstep(seconds, motion.duration - .6, motion.duration));
  });
  if (name === 'side_lying') lying = frames[0];
  motions.push({...motion, frames});
}
const regions = [{name: 'head', bone: '頭', radius: .1}, {name: 'left_hand', bone: '手首.L', radius: .065},
  {name: 'right_hand', bone: '手首.R', radius: .065}, {name: 'chest', bone: '上半身2', radius: .12}, {name: 'body', bone: '下半身', radius: .14}];
const touchFrames = Object.fromEntries(motions.map(motion => [motion.name, motion.frames.map(frame => {
  apply(target, frame); return regions.map(region => worldPosition(target, region.bone).toArray());
})]));
// Sample real linear-skinned vertices for fixed all-motion bounds, using this GLB's inverse binds.
const accessor = index => {
  const attribute = model.accessors[index], view = model.bufferViews[attribute.bufferView];
  const widths = {SCALAR: 1, VEC3: 3, VEC4: 4, MAT4: 16};
  const bytes = {5121: 1, 5123: 2, 5125: 4, 5126: 4}[attribute.componentType];
  const method = {5121: 'getUint8', 5123: 'getUint16', 5125: 'getUint32', 5126: 'getFloat32'}[attribute.componentType];
  const width = widths[attribute.type], stride = view.byteStride ?? width * bytes;
  const buffer = new DataView(binary.buffer, binary.byteOffset, binary.byteLength);
  return Array.from({length: attribute.count}, (_, row) => Array.from({length: width}, (_, column) => buffer[method]((view.byteOffset ?? 0) + (attribute.byteOffset ?? 0) + row * stride + column * bytes, true)));
};
const skin = model.skins[0];
const inverse = accessor(skin.inverseBindMatrices).map(values => new THREE.Matrix4().fromArray(values));
const vertices = model.meshes[0].primitives.filter((_, index) => index !== 11).flatMap(primitive => {
  const positions = accessor(primitive.attributes.POSITION), joints = accessor(primitive.attributes.JOINTS_0), weights = accessor(primitive.attributes.WEIGHTS_0);
  return positions.map((position, index) => ({position, joints: joints[index], weights: weights[index]}));
});
const bounds = new THREE.Box3();
for (const motion of motions) {
  for (let index = 0; index < motion.frames.length; index += 15) {
    apply(target, motion.frames[index]);
    const matrices = skin.joints.map((joint, slot) => target.nodes[joint].matrixWorld.clone().multiply(inverse[slot]));
    for (const vertex of vertices) {
      const point = new THREE.Vector3();
      for (let slot = 0; slot < 4; slot++) if (vertex.weights[slot] > 0) point.add(new THREE.Vector3().fromArray(vertex.position).applyMatrix4(matrices[vertex.joints[slot]]).multiplyScalar(vertex.weights[slot]));
      bounds.expandByPoint(point);
    }
  }
}
const expressions = {normal: {}, happy: {happy: .65}, sad: {sad: .7}, angry: {angry: .7}, surprised: {surprised: .65, o: .2},
  wink: {wink: 1}, sleepy: {blink: .7}, relaxed: {relaxed: .3, happy: .3}, blush: {blush: .65, happy: .25},
  content: {smile: .8, happy: .55}, star_eyes: {star_eye: 1}, heart_eyes: {heart_eye: 1}};
// Keep one complete set of animated channels across clips; invariant joints stay in USD rest transforms.
const animatedJoints = new Set([...mapping.keys(), ...desktop.motions.flatMap(motion => motion.frames[0].map(values => values[0])), ...targetIdle.filter((values, index) => values.some((value, axis) => Math.abs(value - targetRest[index][axis]) > 1e-7)).map(values => values[0])].filter(index => skin.joints.includes(index)));
for (const motion of motions) motion.frames = motion.frames.map(frame => frame.filter(values => animatedJoints.has(values[0])));
const payload = {frameRate: 30, motions, behavior: {expressions, touchRegions: regions, touchFrames},
  posture: {floor: 0, bounds: {min: bounds.min.toArray(), max: bounds.max.toArray()}},
  calibration: {model_sha256: digest, source_model_sha256: source.sha256, mappedJoints: mapping.size, heightRatio,
    method: 'World quaternion deltas from model-specific idle, target-parent local conversion, CCD hand support and palm frames',
    limitations: ['No realtime cloth or ground projection; AVP support/contact requires acceptance']}};
fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, JSON.stringify(payload));
console.log(JSON.stringify({motions: motions.map(motion => motion.name), calibration: payload.calibration, bounds: payload.posture.bounds}));
