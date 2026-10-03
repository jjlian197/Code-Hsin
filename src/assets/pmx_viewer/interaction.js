import * as THREE from './lib/three/three.module.js';

export const touchMotions = {head:'finger_heart', chest:'crossed_arms', hand:'peace', body:'wave'};

// 使用当前变形后的命中点和骨骼坐标，斜侧镜头也不依赖屏幕上的固定矩形。
export function classifyTouch(mesh, hit) {
  const bones=new Map(mesh.skeleton.bones.map(b=>[b.name,b]));
  const world=name=>bones.get(name)?.getWorldPosition(new THREE.Vector3());
  const names=[];
  if(hit.face){
    const indices=mesh.geometry.attributes.skinIndex,weights=mesh.geometry.attributes.skinWeight;
    for(const vertex of [hit.face.a,hit.face.b,hit.face.c])for(let j=0;j<4;j++)
      if(weights.getComponent(vertex,j)>0.25)names.push(mesh.skeleton.bones[indices.getComponent(vertex,j)]?.name||'');
  }
  // 发辫 HairTail 不能当尾巴；手掌挡在胸前时先判断实际命中的手部。
  if(names.some(n=>/^Tail_|尾|しっぽ/i.test(n)))return 'tail';
  if(names.some(n=>/^[右左](手首|[親人中薬小]指)/.test(n))||
      ['右手首','左手首'].some(n=>world(n)?.distanceTo(hit.point)<1.0))return 'hand';
  const head=world('頭'),neck=world('首'),chest=bones.get('上半身2');
  if(head&&neck&&hit.point.y>neck.y&&Math.abs(hit.point.x-head.x)<2.7)return 'head';
  if(chest&&neck){
    const inverse=chest.getWorldQuaternion(new THREE.Quaternion()).invert();
    const origin=chest.getWorldPosition(new THREE.Vector3());
    const local=hit.point.clone().sub(origin).applyQuaternion(inverse);
    const height=neck.clone().sub(origin).applyQuaternion(inverse).y;
    if(height>0&&local.y>height*0.1&&local.y<height*0.9&&Math.abs(local.x)<1.35&&local.z>0.3)return 'chest';
  }
  return 'body';
}

export function reactToTouch(runtime, part, side=1) {
  if(!runtime.behavior.touch(part,side))return false;
  // 外部全身动作和侧躺继续由用户控制；触摸仅在内置站立动作间切换。
  if(!runtime.poseProfile&&runtime.motion in runtime.clips&&touchMotions[part])runtime.play(touchMotions[part]);
  return true;
}
