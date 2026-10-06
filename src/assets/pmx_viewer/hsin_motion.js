import * as THREE from 'three';

// 只适配已验证的原版心；其他角色继续使用自己的骨架与动作。
const forms = new Map([
  ['4cf8454f7a79c84b88cf3dadfaca3fe2d55d3c6349fffd204acaf24dc78ea82e','first'],
  ['e766ffc90c5a69a06da2365232616b1b730d8ecfa08fe685d770da0c509b8471','second'],
]);
export function hsinForm(hash) { return forms.get(hash); }

export function applyHsinChestRig(data, hash) {
  if(!hsinForm(hash))return 0;
  const auxiliaries=data.bones.filter(b=>/^ZSpring_Spine_/.test(b.name));
  if(auxiliaries.length!==10)throw new Error('心的胸部辅助骨结构不匹配');
  const parents=auxiliaries.map(b=>data.bones.findIndex(p=>p.name===(b.name.endsWith('_L')?'左胸':'右胸')));
  if(parents.some(i=>i<0))throw new Error('心的胸部骨骼缺失');
  auxiliaries.forEach((bone,i)=>{bone.parentIndex=parents[i];bone.flag|=0x1000;});
  return auxiliaries.length;
}

export function runningClip(data, mesh) {
  const names=new Set(mesh.skeleton.bones.map(b=>b.name));
  const tracks=data.tracks.map(track=>{
    const name=track.name.match(/^\.bones\[(.+)\]\.(quaternion|position)$/);
    if(!name||!names.has(name[1]))throw new Error('跑步动作与模型不匹配');
    const Type=track.type==='quaternion'?THREE.QuaternionKeyframeTrack:THREE.VectorKeyframeTrack;
    // 关键帧和总时长一起翻倍，物理仍以真实帧间隔推进。
    return new Type(track.name,track.times.map(t=>t*2),track.values);
  });
  const clip=new THREE.AnimationClip('treadmill_running',data.duration*2,tracks);
  if(!clip.validate())throw new Error('跑步动作关键帧无效');
  return clip;
}
