import * as THREE from 'three';
import { createCalibratedGestures } from './calibrated_gestures.js';
import {RIG_SCHEMA} from './rig/schema.js';
import {HEART_POSE} from './heart_pose.js';

// 复杂手势只开放给已经验证的心双形态；标准骨名不能证明其他角色已校准。
const calibratedModels = new Set([
  '4cf8454f7a79c84b88cf3dadfaca3fe2d55d3c6349fffd204acaf24dc78ea82e',
  'e766ffc90c5a69a06da2365232616b1b730d8ecfa08fe685d770da0c509b8471',
]);

function rotationTrack(name, times, angles) {
  if (times.length !== angles.length) throw new Error(`动作关键帧数量不一致：${name}`);
  const values = angles.flatMap(([x = 0, y = 0, z = 0]) =>
    new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z)).toArray());
  return new THREE.QuaternionKeyframeTrack(`.bones[${name}].quaternion`, times, values);
}

export function createBuiltinClips(mesh, rig = null) {
  const names = new Set(mesh.skeleton.bones.map(b => b.name));
  const semantic = new Map(RIG_SCHEMA.map(s=>[s.aliases[0],s.id]));
  const track = (name, times, angles) => {
    const index = rig?.index(semantic.get(name));
    if (rig) return index === undefined ? [] : [rotationTrack(rig.usesOriginalNames?rig.get(semantic.get(name)).name:index,times,angles)];
    return names.has(name) ? [rotationTrack(name,times,angles)] : [];
  };
  const t = [0, 1, 2, 3, 4];
  const idle = new THREE.AnimationClip('idle', 4, [
    // 手臂的底层旋转固定；呼吸由行为层处理，避免待机摆动让双手接触点漂移。
    ...track('右腕', t, t.map(() => [0, 0, 0.67])),
    ...track('左腕', t, t.map(() => [0, 0, -0.67])),
    ...track('右ひじ', t, t.map(() => [0, 0, 0])),
    ...track('右手首', t, t.map(() => [0, 0, 0])),
    ...track('左ひじ', t, t.map(() => [0, 0, 0])),
    ...track('左手首', t, t.map(() => [0, 0, 0])),
    ...(rig ? RIG_SCHEMA.filter(s=>s.group==='finger').map(s=>s.aliases[0]) :
      mesh.skeleton.bones.filter(b => /^[右左](親|人|中|薬|小)指[０１２３]$/.test(b.name)).map(b=>b.name))
      .flatMap(name => track(name, t, t.map(() => [0,0,0]))),
    ...track('上半身', t, t.map(v => [0, 0, 0])),
    ...track('上半身2', t, t.map(v => [0, 0, 0])),
    ...track('頭', t, t.map(v => [0, 0, 0])),
  ]);
  const nod = new THREE.AnimationClip('nod', 1.6,
    track('頭', [0, 0.3, 0.6, 0.9, 1.2, 1.6], [[0], [0.18], [-0.04], [0.15], [0.02], [0]]));
  const legacyBones=[...HEART_POSE.map(p=>p.name),'上半身2','センター',
    ...['右','左'].flatMap(side=>['親','人','中','薬','小'].map(finger=>side+finger+'指先'))];
  if (rig && (!calibratedModels.has(rig.report.model.sha256) || !rig.usesOriginalNames || !legacyBones.every(name=>names.has(name)))) {
    nod.blendMode = THREE.AdditiveAnimationBlendMode;
    return nod.tracks.length ? {idle,nod} : {idle};
  }
  const wave = createWaveClip(mesh);
  nod.blendMode = wave.blendMode = THREE.AdditiveAnimationBlendMode;
  return { idle, nod, wave, ...createGestureClips(mesh), ...createCalibratedGestures(mesh) };
}

// 用真实手指方向建立掌面坐标系，避免把手腕某个欧拉轴误当作掌心方向。
export function palmNormal(mesh, side='右') {
  const bones = new Map(mesh.skeleton.bones.map(b => [b.name, b]));
  const position = name => bones.get(name)?.getWorldPosition(new THREE.Vector3());
  const wrist = position(side+'手首'), middle = position(side+'中指２');
  const index = position(side+'人指１'), little = position(side+'小指１');
  if (!wrist || !middle || !index || !little) return null;
  return new THREE.Vector3().crossVectors(index.sub(little), middle.sub(wrist)).normalize().multiplyScalar(side==='右'?1:-1);
}

function createWaveClip(mesh) {
  const bones = new Map(mesh.skeleton.bones.map(b => [b.name, b]));
  const names = ['右腕', '右ひじ', '右手首'];
  for (const name of [...names, '右中指２', '右人指１', '右小指１']) {
    if (!bones.has(name)) throw new Error(`挥手缺少骨骼：${name}`);
  }
  const initial = new Map(mesh.skeleton.bones.map(b => [b, b.quaternion.clone()]));
  const update = () => mesh.updateMatrixWorld(true);
  const position = name => bones.get(name).getWorldPosition(new THREE.Vector3());
  const capture = () => new Map(names.map(name => [name, bones.get(name).quaternion.clone()]));
  const worldRotation = (bone, q) => {
    bone.quaternion.copy(bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(q));
    update();
  };
  const aim = (name, child, direction) => {
    const bone = bones.get(name);
    const delta = new THREE.Quaternion().setFromUnitVectors(
      position(child).sub(position(name)).normalize(), new THREE.Vector3(...direction).normalize());
    worldRotation(bone, delta.multiply(bone.getWorldQuaternion(new THREE.Quaternion())));
  };
  try {
    bones.get('右腕').quaternion.setFromEuler(new THREE.Euler(0, 0, 0.67));
    update();
    const rest = capture();
    const wristWorld = bones.get('右手首').getWorldQuaternion(new THREE.Quaternion());
    const up = position('右中指２').sub(position('右手首')).normalize();
    const normal = palmNormal(mesh);
    const palmFrame = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3().crossVectors(up, normal).normalize(), up, normal));
    aim('右腕', '右ひじ', [-0.9, -0.3, 0.12]);
    aim('右ひじ', '右手首', [0.12, 1, 0.15]);
    const targetUp = new THREE.Vector3(-0.08, 1, 0).normalize();
    const targetNormal = new THREE.Vector3(0, 0, 1); // 正面镜头位于 +Z。
    const targetFrame = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3().crossVectors(targetUp, targetNormal).normalize(), targetUp, targetNormal));
    worldRotation(bones.get('右手首'), targetFrame.multiply(palmFrame.invert()).multiply(wristWorld));
    const greeting = capture();
    const times = [0, 0.25, 0.5, 0.8, 1.15, 1.5, 1.85, 2.2, 2.6, 3];
    const values = new Map(names.map(name => [name, []]));
    const ease = t => { t = THREE.MathUtils.clamp(t, 0, 1); return t * t * (3 - 2 * t); };
    for (const t of times) {
      const weight = t < 0.8 ? ease(t / 0.8) : t > 2.2 ? ease((3 - t) / 0.8) : 1;
      for (const name of names) bones.get(name).quaternion.slerpQuaternions(rest.get(name), greeting.get(name), weight);
      update();
      if (t >= 0.8 && t <= 2.2) {
        const sway = 0.22 * Math.sin((t - 0.8) * Math.PI * 2 / 0.7);
        const wrist = bones.get('右手首');
        worldRotation(wrist, new THREE.Quaternion().setFromAxisAngle(targetNormal, sway)
          .multiply(wrist.getWorldQuaternion(new THREE.Quaternion())));
      }
      // 加法动作相对于手臂下垂的待机姿态，首尾都是单位增量。
      for (const name of names) values.get(name).push(...rest.get(name).clone().invert()
        .multiply(bones.get(name).quaternion).normalize().toArray());
    }
    return new THREE.AnimationClip('wave', 3, names.map(name =>
      new THREE.QuaternionKeyframeTrack(`.bones[${name}].quaternion`, times, values.get(name))));
  } finally {
    initial.forEach((q, bone) => bone.quaternion.copy(q));
    update();
  }
}

// 用真实关节位置求肩/肘方向，手指弯向掌心，不依赖模型局部轴猜测。
function createGestureClips(mesh) {
  const bones=new Map(mesh.skeleton.bones.map(b=>[b.name,b]));
  const initial=new Map(mesh.skeleton.bones.map(b=>[b,b.quaternion.clone()]));
  const names=[...bones.keys()].filter(n=>/^[右左](腕|ひじ|手首|(親|人|中|薬|小)指[０１２３])$/.test(n));
  const update=()=>mesh.updateMatrixWorld(true);
  const position=n=>bones.get(n).getWorldPosition(new THREE.Vector3());
  const worldRotation=(name,q)=>{
    const b=bones.get(name);b.quaternion.copy(b.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(q));update();
  };
  const aim=(name,child,direction)=>{
    const delta=new THREE.Quaternion().setFromUnitVectors(position(child).sub(position(name)).normalize(),direction.clone().normalize());
    worldRotation(name,delta.multiply(bones.get(name).getWorldQuaternion(new THREE.Quaternion())));
  };
  const frames=new Map();
  let curlNormal=new THREE.Vector3(0,0,1);
  const setPalm=(side,up,normal=new THREE.Vector3(0,0,1))=>{
    const [frame,wrist]=frames.get(side);
    up=up.clone().normalize();
    const target=new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3().crossVectors(up,normal).normalize(),up,normal));
    worldRotation(side+'手首',target.multiply(frame.clone().invert()).multiply(wrist));
  };
  const bend=(name,child,angle)=>{
    const direction=position(child).sub(position(name)).normalize();
    const axis=new THREE.Vector3().crossVectors(direction,curlNormal).normalize();
    worldRotation(name,new THREE.Quaternion().setFromAxisAngle(axis,angle)
      .multiply(bones.get(name).getWorldQuaternion(new THREE.Quaternion())));
  };
  const curl=(side,finger,angles)=>{
    const joints=['１','２','３','先'];
    angles.forEach((angle,i)=>bend(side+finger+'指'+joints[i],side+finger+'指'+joints[i+1],angle));
  };
  const raised=()=>{
    aim('右腕','右ひじ',new THREE.Vector3(-0.9,-0.3,0.12));
    aim('右ひじ','右手首',new THREE.Vector3(0.12,1,0.15));
    setPalm('右',new THREE.Vector3(-0.08,1,0));
  };
  try {
    bones.get('右腕').quaternion.setFromEuler(new THREE.Euler(0,0,0.67));
    bones.get('左腕').quaternion.setFromEuler(new THREE.Euler(0,0,-0.67));update();
    const rest=new Map(names.map(n=>[n,bones.get(n).quaternion.clone()]));
    for(const side of ['右','左']) {
      const up=position(side+'中指２').sub(position(side+'手首')).normalize(),normal=palmNormal(mesh,side);
      frames.set(side,[new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
        new THREE.Vector3().crossVectors(up,normal).normalize(),up,normal)),bones.get(side+'手首').getWorldQuaternion(new THREE.Quaternion())]);
    }
    const clip=(name,pose)=>{
      curlNormal.set(0,0,1);
      for(const [n,q] of rest)bones.get(n).quaternion.copy(q);update();pose();
      const times=[0,0.45,0.9,2.6,3.6],weights=[0,0.5,1,1,0];
      const tracks=names.map(n=>{
        const delta=rest.get(n).clone().invert().multiply(bones.get(n).quaternion).normalize();
        return new THREE.QuaternionKeyframeTrack(`.bones[${n}].quaternion`,times,
          weights.flatMap(w=>new THREE.Quaternion().slerp(delta,w).toArray()));
      });
      const value=new THREE.AnimationClip(name,3.6,tracks);value.blendMode=THREE.AdditiveAnimationBlendMode;return value;
    };
    const peace=clip('peace',()=>{
      raised();curl('右','薬',[0.85,1.05,0.65]);curl('右','小',[0.9,1.0,0.65]);
      bend('右親指１','右親指２',0.85);bend('右親指２','右親指先',0.5);
      for(const [finger,spread] of [['人',-0.12],['中',0.12]]) {
        const name='右'+finger+'指１';worldRotation(name,new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),spread)
          .multiply(bones.get(name).getWorldQuaternion(new THREE.Quaternion())));
      }
    });
    return {peace};
  } finally {
    initial.forEach((q,b)=>b.quaternion.copy(q));update();
  }
}
