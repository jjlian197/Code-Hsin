import * as THREE from './lib/three/three.module.js';
import { HEART_POSE } from './heart_pose.js';
import {gestureBones} from './gesture_bones.js';
import {isAemeathChestModel} from './aemeath_physics.js';

const vector = () => new THREE.Vector3();
const quaternion = () => new THREE.Quaternion();
const ease = t => { const x = THREE.MathUtils.clamp(t, 0, 1); return x*x*x*(x*(x*6-15)+10); };

export function gestureGeometry(mesh) {
  const points = Object.fromEntries([...gestureBones(mesh)].filter(([name]) => /^(頭|首|上半身2|センター|[右左](腕|ひじ|手首|(親|人|中|薬|小)指[１２３先]))$/.test(name))
    .map(([name,b]) => [name, b.getWorldPosition(vector()).toArray()]));
  const p = n => new THREE.Vector3(...points[n]);
  const lower = ['中', '薬', '小'].map(finger => {
    const directions = ['左', '右'].map(side => p(side+finger+'指先').sub(p(side+finger+'指１')));
    directions.forEach(d => { d.z=0; d.normalize(); });
    const bends = ['左', '右'].map(side => {
      const joints = ['１', '２', '３', '先'].map(n => side+finger+'指'+n);
      const segments = joints.slice(0, -1).map((n, i) => p(joints[i+1]).sub(p(n)).normalize());
      return [THREE.MathUtils.radToDeg(segments[0].angleTo(segments[1])), THREE.MathUtils.radToDeg(segments[1].angleTo(segments[2]))];
    });
    return {finger, corner:THREE.MathUtils.radToDeg(directions[0].angleTo(directions[1])), bends};
  });
  return {points, lower, palmDistance:p('左手首').distanceTo(p('右手首')),
    indexGap:p('左人指先').distanceTo(p('右人指先'))};
}

// 沿用参考项目的轮廓求解，直接使用心的 PMX 骨长，不套用 GLB 的绑定坐标或缩放。
export function createCalibratedGestures(mesh, rig = null) {
  const bones = gestureBones(mesh);
  const names = HEART_POSE.map(p => p.name);
  const sides = ['左', '右'];
  for (const name of [...names, '上半身2', 'センター', ...sides.flatMap(side =>
    ['親', '人', '中', '薬', '小'].map(finger => side+finger+'指先'))]) {
    if (!bones.has(name)) throw new Error(`手势校准缺少骨骼：${name}`);
  }
  const original = new Map(mesh.skeleton.bones.map(b => [b, b.quaternion.clone()]));
  const bind = new Map(names.map(n => [n, bones.get(n).quaternion.clone()]));
  const update = () => mesh.updateMatrixWorld(true);
  const pos = name => bones.get(name).getWorldPosition(vector());
  const capture = () => new Map(names.map(n => [n, bones.get(n).quaternion.clone()]));
  const restore = pose => { pose.forEach((q, n) => bones.get(n).quaternion.copy(q)); update(); };
  const setWorld = (name, q) => {
    const bone = bones.get(name);
    bone.quaternion.copy(bone.parent.getWorldQuaternion(quaternion()).invert().multiply(q)).normalize();
    update();
  };
  const aim = (name, child, target) => {
    const delta = quaternion().setFromUnitVectors(pos(child).sub(pos(name)).normalize(), target.clone().sub(pos(name)).normalize());
    setWorld(name, delta.multiply(bones.get(name).getWorldQuaternion(quaternion())));
  };
  const solveChain = (root, joint, end, target, hint) => {
    const origin = pos(root), a = origin.distanceTo(pos(joint)), b = pos(joint).distanceTo(pos(end));
    const direction = target.clone().sub(origin);
    const d = THREE.MathUtils.clamp(direction.length(), Math.abs(a-b)+1e-5, a+b-1e-5);
    direction.normalize();
    const along = (a*a-b*b+d*d)/(2*d), radius = Math.sqrt(Math.max(0, a*a-along*along));
    const pole = hint.clone().addScaledVector(direction, -hint.dot(direction)).normalize();
    const bend = origin.clone().addScaledVector(direction, along).addScaledVector(pole, radius);
    aim(root, joint, bend); aim(joint, end, origin.addScaledVector(direction, d));
  };
  const arm = (side, target) => {
    const wrist = side+'手首', orientation = bones.get(wrist).getWorldQuaternion(quaternion());
    solveChain(side+'腕', side+'ひじ', wrist, target, new THREE.Vector3(side==='左'?1:-1, -1, 0.18));
    setWorld(wrist, orientation);
  };
  const chain = (side, finger) => ['１', '２', '３', '先'].map(n => side+finger+'指'+n);
  const clip = (name, target, duration, weight, metadata) => {
    // 密集采样五次缓动；播放时只插值局部旋转，不受窗口大小影响。
    const times = Array.from({length: Math.ceil(duration*30)+1}, (_, i) => Math.min(i/30, duration));
    const tracks = names.map(n => {
      const delta = idle.get(n).clone().invert().multiply(target.get(n)).normalize();
      return new THREE.QuaternionKeyframeTrack(`.bones[${n}].quaternion`, times,
        times.flatMap(t => quaternion().slerp(delta, weight(n, t)).toArray()));
    });
    const result = new THREE.AnimationClip(name, duration, tracks);
    result.blendMode = THREE.AdditiveAnimationBlendMode;
    result.userData = metadata;
    return result;
  };
  let idle;
  try {
    bones.get('右腕').quaternion.setFromEuler(new THREE.Euler(0, 0, 0.67));
    bones.get('左腕').quaternion.setFromEuler(new THREE.Euler(0, 0, -0.67));
    update(); idle = capture();
    const height = pos('頭').y-pos('センター').y;
    const bodyScale = height/8.75;

    // MMDLoader 已将 PMX 转为右手坐标：VPD 同样翻转四元数 X/Y，不使用 GLB 的 B^-1 Δ B。
    for (const p of HEART_POSE) {
      const [x, y, z, w] = p.rotation;
      bones.get(p.name).quaternion.copy(bind.get(p.name)).multiply(new THREE.Quaternion(-x, -y, z, w).normalize());
    }
    update();
    const tips = side => [pos(side+'人指先'), pos(side+'親指先')];
    const midpoint = side => { const [a, b] = tips(side); return a.add(b).multiplyScalar(0.5); };
    const axis = sides.map(side => { const [a, b] = tips(side); return b.sub(a).normalize(); })
      .reduce((a, b) => a.add(b), vector()).normalize();
    for (const side of sides) {
      const [a, b] = tips(side);
      setWorld(side+'手首', quaternion().setFromUnitVectors(b.sub(a).normalize(), axis)
        .multiply(bones.get(side+'手首').getWorldQuaternion(quaternion())));
    }
    // 爱弥斯的上半身1在上半身2之上；比心以实际上胸为基准。
    const chest = pos(isAemeathChestModel(rig?.report.model.sha256)?rig.upperTorso().name:'上半身2');
    const center = chest.clone().add(new THREE.Vector3(0, 0.65*bodyScale, 2.8*bodyScale));
    for (const side of sides) arm(side, pos(side+'手首').add(center.clone().sub(midpoint(side))));

    const handScale = pos('左人指１').distanceTo(pos('左人指２'))/0.03;
    const lowerApex = pos('左親指先').add(pos('右親指先')).multiplyScalar(0.5);
    lowerApex.y -= 0.026*handScale; lowerApex.z -= 0.008*handScale;
    for (const side of sides) solveChain(side+'親指１', side+'親指２', side+'親指先', lowerApex, new THREE.Vector3(0, 0, -1));
    const contactX = (pos('左人指先').x+pos('右人指先').x)/2;
    const upperContact = pos('左人指先').add(pos('右人指先')).multiplyScalar(0.5);
    let spread = 0;
    const originalPalmDistance = pos('左手首').distanceTo(pos('右手首'));
    const specs = [];
    for (const side of sides) {
      const sign = side==='左'?1:-1, laneDepth = pos(side+'中指１').z;
      for (const [row, finger] of ['中', '薬', '小'].entries()) {
        const joints = chain(side, finger), origin = pos(joints[0]);
        const length = joints.slice(0, -1).reduce((total, n, i) => total+pos(n).distanceTo(pos(joints[i+1])), 0);
        const laneZ = laneDepth+row*0.010*handScale, dz = laneZ-origin.z;
        const span = Math.sqrt(Math.max(0, (length*length-dz*dz)/2));
        spread = Math.max(spread, span-sign*(origin.x-contactX)+0.003*handScale);
        specs.push({side, sign, finger, joints, span, laneZ});
      }
    }
    for (const side of sides) arm(side, pos(side+'手首').add(new THREE.Vector3((side==='左'?1:-1)*spread, 0, 0)));
    // 先按实际长指外移手掌，再接合上方食指；不靠过度屈曲补偿掌距。
    upperContact.y -= 0.012*handScale;
    upperContact.z = (pos('左人指１').z+pos('右人指１').z)/2;
    for (const side of sides) {
      const joints = chain(side, '人');
      joints.slice(0, -1).forEach(n => bones.get(n).quaternion.copy(bind.get(n))); update();
      const distalLength = pos(joints[2]).distanceTo(pos(joints[3]));
      const target = upperContact.clone();
      target.x += (side==='左'?-1:1)*0.0025*handScale;
      const direction = new THREE.Vector3(side==='左'?-0.8:0.8, -0.6, 0);
      const distalTarget = target.clone().addScaledVector(direction, -distalLength);
      solveChain(joints[0], joints[1], joints[2], distalTarget, new THREE.Vector3(0, 1, 0));
      aim(joints[2], joints[3], target);
    }
    for (const {joints, sign, span, laneZ} of specs) {
      joints.slice(0, -1).forEach(n => bones.get(n).quaternion.copy(bind.get(n))); update();
      const origin = pos(joints[0]);
      const target = new THREE.Vector3(origin.x-sign*span, origin.y-span, laneZ);
      const direction = target.sub(origin).normalize();
      joints.slice(0, -1).forEach((n, i) => aim(n, joints[i+1], pos(n).add(direction)));
    }
    const heart = capture();
    const heartMetadata = {profile:'hsin_dual_heart', reference:'heartmark001',
      palmDistance:pos('左手首').distanceTo(pos('右手首')), originalPalmDistance, spreadPerSide:spread};

    // 双手交叉是胸前 X 手势，不是抱臂；两条前臂错开深度，掌心朝向 +Z 镜头。
    restore(idle);
    const frames = new Map();
    for (const side of sides) {
      const y = pos(side+'中指２').sub(pos(side+'手首')).normalize();
      const z = vector().crossVectors(pos(side+'人指１').sub(pos(side+'小指１')), y).normalize()
        .multiplyScalar(side==='右'?1:-1);
      const frame = quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(vector().crossVectors(y, z).normalize(), y, z));
      frames.set(side, frame.invert().multiply(bones.get(side+'手首').getWorldQuaternion(quaternion())));
    }
    const crossCenter = pos('上半身2').add(new THREE.Vector3(0, 0.35*bodyScale, 3.5*bodyScale));
    for (const side of sides) {
      const sign = side==='左'?1:-1;
      arm(side, crossCenter.clone().add(new THREE.Vector3(-sign*1.1*bodyScale, 1.55*bodyScale, sign*0.45*bodyScale)));
      const y = new THREE.Vector3(-sign*0.55, 0.835, 0).normalize(), z = new THREE.Vector3(0, 0, 1);
      const frame = quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(vector().crossVectors(y, z).normalize(), y, z));
      setWorld(side+'手首', frame.multiply(frames.get(side)));
      // 保持自然的伸指，抹平绑定指骨的轻微折线；不把交叉手势做成握拳。
      for (const finger of ['人', '中', '薬', '小']) {
        const joints = chain(side, finger), direction = pos(joints[3]).sub(pos(joints[0])).normalize();
        joints.slice(0, -1).forEach((n, i) => aim(n, joints[i+1], pos(n).add(direction)));
      }
    }
    bones.get('頭').quaternion.multiply(quaternion().setFromEuler(new THREE.Euler(0.10, 0, -0.045)));
    const cross = capture();
    const heartWeight = (name, t) => {
      if (name==='頭'||name==='首') return t<1.6?ease((t-1.3)/0.3):t<2.5?1:1-ease((t-2.5)/0.8);
      if (/指|手首|手捩/.test(name)) return t<1.3?ease((t-0.35)/0.95):t<2.5?1:1-ease((t-2.5)/0.8);
      return t<1.3?ease(t/1.3):t<2.5?1:1-ease((t-2.5)/1.2);
    };
    return {
      finger_heart:clip('finger_heart', heart, 3.7, heartWeight, heartMetadata),
      crossed_arms:clip('crossed_arms', cross, 4.8, (name, t) => t<1.1?ease(t/1.1):t<3.2?1:1-ease((t-3.2)/1.6), {profile:'hsin_cross_x'}),
    };
  } finally {
    original.forEach((q, bone) => bone.quaternion.copy(q)); update();
  }
}
