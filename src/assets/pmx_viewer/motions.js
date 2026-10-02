import * as THREE from 'three';

function rotationTrack(name, times, angles) {
  if (times.length !== angles.length) throw new Error(`动作关键帧数量不一致：${name}`);
  const values = angles.flatMap(([x = 0, y = 0, z = 0]) =>
    new THREE.Quaternion().setFromEuler(new THREE.Euler(x, y, z)).toArray());
  return new THREE.QuaternionKeyframeTrack(`.bones[${name}].quaternion`, times, values);
}

export function createBuiltinClips(mesh) {
  const names = new Set(mesh.skeleton.bones.map(b => b.name));
  const track = (name, times, angles) => names.has(name) ? [rotationTrack(name, times, angles)] : [];
  const t = [0, 1, 2, 3, 4];
  const idle = new THREE.AnimationClip('idle', 4, [
    ...track('右腕', t, t.map(v => [0, 0, 0.67 + Math.sin(v * Math.PI / 2) * 0.008])),
    ...track('左腕', t, t.map(v => [0, 0, -0.67 - Math.sin(v * Math.PI / 2) * 0.008])),
    ...track('右ひじ', t, t.map(() => [0, 0, 0])),
    ...track('右手首', t, t.map(() => [0, 0, 0])),
    ...track('上半身', t, t.map(v => [0, 0, 0])),
    ...track('上半身2', t, t.map(v => [0, 0, 0])),
    ...track('頭', t, t.map(v => [0, 0, 0])),
  ]);
  const nod = new THREE.AnimationClip('nod', 1.6,
    track('頭', [0, 0.3, 0.6, 0.9, 1.2, 1.6], [[0], [0.18], [-0.04], [0.15], [0.02], [0]]));
  const wave = createWaveClip(mesh);
  nod.blendMode = wave.blendMode = THREE.AdditiveAnimationBlendMode;
  return { idle, nod, wave };
}

// 用真实手指方向建立掌面坐标系，避免把手腕某个欧拉轴误当作掌心方向。
export function palmNormal(mesh) {
  const bones = new Map(mesh.skeleton.bones.map(b => [b.name, b]));
  const position = name => bones.get(name)?.getWorldPosition(new THREE.Vector3());
  const wrist = position('右手首'), middle = position('右中指２');
  const index = position('右人指１'), little = position('右小指１');
  if (!wrist || !middle || !index || !little) return null;
  return new THREE.Vector3().crossVectors(index.sub(little), middle.sub(wrist)).normalize();
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
