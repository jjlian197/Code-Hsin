import * as THREE from 'three';

export function transitionAssets(data, expectedHash, mesh) {
  if(data?.version!==1||data.model_sha256!==expectedHash)throw new Error('侧躺过渡与当前 PMX 不匹配，请重新生成动作');
  if(!Number.isFinite(data.floor)||!data.bounds||[...data.bounds.min,...data.bounds.max].some(x=>!Number.isFinite(x)))
    throw new Error('侧躺过渡地面或取景范围无效');
  const boneNames=new Set(mesh.skeleton.bones.map(b=>b.name));
  const read=track=>{
    const name=track.name.match(/^\.bones\[(.+)\]\.(quaternion|position)$/);
    if(!name||!boneNames.has(name[1]))throw new Error('过渡动作包含未知骨骼');
    const size=track.type==='quaternion'?4:track.type==='vector'?3:0;
    if(!size||track.values.length!==track.times.length*size||!track.times.length||
      [...track.values,...track.times].some(x=>!Number.isFinite(x))||track.times.some((t,i)=>t<0||(i&&t<=track.times[i-1])))
      throw new Error('过渡动作关键帧无效');
    return size===4?new THREE.QuaternionKeyframeTrack(track.name,track.times,track.values):new THREE.VectorKeyframeTrack(track.name,track.times,track.values);
  };
  const clips={};
  for(const name of ['lie_down','get_up']){
    const source=data.clips?.[name];
    if(!source||!Number.isFinite(source.duration)||source.duration<=0||source.duration>30)throw new Error('过渡动作时长无效');
    const freeze=data.freeze.map(track=>({...track,times:[0,source.duration],values:[...track.values,...track.values]}));
    const clip=new THREE.AnimationClip(name,source.duration,[...source.tracks,...freeze].map(read));
    if(!clip.validate()||clip.tracks.some(t=>t.times.at(-1)>clip.duration+.001))throw new Error('过渡动作时间范围无效');
    clips[name]=clip;
  }
  const hold=clips.lie_down.tracks.map(track=>{
    const size=track.getValueSize(),value=Array.from(track.values.slice(-size));
    return new track.constructor(track.name,[0,1],[...value,...value]);
  });
  clips.side_lying=new THREE.AnimationClip('side_lying',1,hold);
  const bounds=new THREE.Box3(new THREE.Vector3().fromArray(data.bounds.min),new THREE.Vector3().fromArray(data.bounds.max));
  bounds.expandByScalar(2.5);bounds.min.y=data.floor;
  return {floor:data.floor,bounds,clips};
}

// 从真正显示的姿势进入，避免触摸手势或站立物理残留在第一帧跳回绑定姿态。
export function blendFromCurrent(clip, mesh, duration=.35) {
  const bones=new Map(mesh.skeleton.bones.map(b=>[b.name,b]));
  return new THREE.AnimationClip(clip.name,clip.duration+duration,clip.tracks.map(track=>{
    const [,name,property]=track.name.match(/^\.bones\[(.+)\]\.(quaternion|position)$/);
    const first=bones.get(name)[property].toArray();
    const values=[...first,...first,...track.values];
    return new track.constructor(track.name,[0,duration*.15,...Array.from(track.times,t=>t+duration)],values);
  }));
}
