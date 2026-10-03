import * as THREE from 'three';
import { FBXLoader } from './lib/three/addons/loaders/FBXLoader.js';
import { palmNormal } from './motions.js';

const v=()=>new THREE.Vector3(),q=()=>new THREE.Quaternion();
const normalizeName=name=>name.replace(/[^a-zA-Z0-9]/g,'');

export async function loadLayingPose(url,mesh) {
  const asset=await new FBXLoader().loadAsync(url);
  try {return retargetLayingPose(asset,mesh);}
  finally {asset.traverse(node=>{node.geometry?.dispose();for(const mat of [].concat(node.material||[]))mat.dispose();});}
}

export function retargetLayingPose(asset,mesh) {
  const clip=asset.animations.find(c=>c.tracks.length>20);
  if(!clip||clip.duration>0.2)throw new Error('需要 Female Laying Pose 定格 FBX，不支持在此入口加载舞蹈');
  const source=new Map();asset.traverse(b=>{if(b.isBone&&!source.has(normalizeName(b.name)))source.set(normalizeName(b.name),b);});
  const s=name=>source.get('mixamorig'+name);
  for(const name of ['Hips','Spine','Spine1','Spine2','Head',...['Right','Left'].flatMap(side=>['Shoulder','Arm','ForeArm','Hand','HandMiddle2','HandIndex1','HandPinky1','UpLeg','Leg','Foot'].map(name=>side+name))])
    if(!s(name))throw new Error('FBX 缺少 Mixamo 骨骼：'+name);
  asset.updateMatrixWorld(true);
  const sourceRest=new Map([...source].map(([name,b])=>[name,{position:b.getWorldPosition(v()),rotation:b.getWorldQuaternion(q())}]));
  const mixer=new THREE.AnimationMixer(asset);mixer.clipAction(clip).play();mixer.update(0);asset.updateMatrixWorld(true);
  const bones=new Map(mesh.skeleton.bones.map(b=>[b.name,b]));
  const saved=new Map(mesh.skeleton.bones.map(b=>[b,{position:b.position.clone(),rotation:b.quaternion.clone()}]));
  const update=()=>mesh.updateMatrixWorld(true);
  const p=name=>bones.get(name).getWorldPosition(v());
  const sp=name=>s(name).getWorldPosition(v());
  const worldRotation=(name,rotation)=>{const b=bones.get(name);b.quaternion.copy(b.parent.getWorldQuaternion(q()).invert().multiply(rotation)).normalize();update();};
  const aimDirection=(name,child,direction)=>{
    const b=bones.get(name),delta=q().setFromUnitVectors(p(child).sub(p(name)).normalize(),direction.normalize());
    worldRotation(name,delta.multiply(b.getWorldQuaternion(q())));
  };
  const aim=(name,child,start,end)=>aimDirection(name,child,sp(end).sub(sp(start)));
  try {
    mesh.pose();update();
    const targetRest=new Map(mesh.skeleton.bones.map(b=>[b.name,b.getWorldQuaternion(q())]));
    const center=bones.get('センター'),hipsRest=p('下半身');
    const scale=hipsRest.y/sourceRest.get('mixamorigHips').position.y;
    const rootRotation=s('Hips').getWorldQuaternion(q()).multiply(sourceRest.get('mixamorigHips').rotation.clone().invert());
    const hipOffset=hipsRest.sub(p('センター'));
    center.quaternion.copy(rootRotation);
    center.position.copy(sp('Hips').multiplyScalar(scale).sub(hipOffset.applyQuaternion(rootRotation)));
    update();
    // 以世界朝向差重映射躯干，再以真实关节方向消除 Mixamo T 姿态与 PMX A 姿态的差异。
    for(const [from,to] of [['Spine','上半身'],['Spine1','上半身1'],['Spine2','上半身2'],['Neck','首'],['Head','頭']]){
      if(!s(from)||!bones.has(to))continue;
      worldRotation(to,s(from).getWorldQuaternion(q()).multiply(sourceRest.get('mixamorig'+from).rotation.clone().invert()).multiply(targetRest.get(to)));
    }
    for(const [side,word] of [['右','Right'],['左','Left']]){
      aim(side+'肩',side+'腕',word+'Shoulder',word+'Arm');
      aim(side+'腕',side+'ひじ',word+'Arm',word+'ForeArm');
      aim(side+'ひじ',side+'手首',word+'ForeArm',word+'Hand');
      const wrist=bones.get(side+'手首'),up=p(side+'中指２').sub(p(side+'手首')).normalize();
      const normal=palmNormal(mesh,side),restFrame=q().setFromRotationMatrix(new THREE.Matrix4().makeBasis(v().crossVectors(up,normal).normalize(),up,normal));
      const desiredUp=sp(word+'HandMiddle2').sub(sp(word+'Hand')).normalize();
      const desiredNormal=v().crossVectors(sp(word+'HandIndex1').sub(sp(word+'HandPinky1')),desiredUp).normalize().multiplyScalar(side==='右'?1:-1);
      const desiredFrame=q().setFromRotationMatrix(new THREE.Matrix4().makeBasis(v().crossVectors(desiredUp,desiredNormal).normalize(),desiredUp,desiredNormal));
      worldRotation(side+'手首',desiredFrame.multiply(restFrame.invert()).multiply(wrist.getWorldQuaternion(q())));
      // 原文件的深屈膝适用于短衣；心的长裙改用较浅屈膝，双腿顺着裙摆叠放。
      const thigh=sp(word+'Leg').sub(sp(word+'UpLeg')).normalize();
      const calf=sp(word+'Foot').sub(sp(word+'Leg')).normalize();
      if(side==='右'){
        thigh.lerp(sp('LeftLeg').sub(sp('LeftUpLeg')).normalize(),0.90).normalize();
        calf.lerp(sp('LeftFoot').sub(sp('LeftLeg')).normalize(),0.85).normalize();
      }
      aimDirection(side+'足',side+'ひざ',thigh);
      aimDirection(side+'ひざ',side+'足首',calf);
      if(bones.has(side+'つま先')&&s(word+'ToeBase'))aim(side+'足首',side+'つま先',word+'Foot',word+'ToeBase');
    }
    const tracked=['センター','上半身','上半身1','上半身2','首','頭',...['右','左'].flatMap(side=>['肩','腕','ひじ','手首','足','ひざ','足首'].map(n=>side+n))];
    const tracks=tracked.filter(name=>bones.has(name)).map(name=>new THREE.QuaternionKeyframeTrack(`.bones[${name}].quaternion`,[0,1], [...bones.get(name).quaternion.toArray(),...bones.get(name).quaternion.toArray()]));
    // 定格服装/头发使用模型绑定姿态，不能继承刚才站立时物理积累的随机偏移。
    const dynamic=new Set((mesh.geometry.userData.MMD?.rigidBodies||[]).filter(b=>b.type>0&&b.boneIndex>=0).map(b=>mesh.skeleton.bones[b.boneIndex]));
    for(const bone of dynamic){
      if(tracked.includes(bone.name))continue;
      tracks.push(new THREE.QuaternionKeyframeTrack(`.bones[${bone.name}].quaternion`,[0,1],[...bone.quaternion.toArray(),...bone.quaternion.toArray()]));
      tracks.push(new THREE.VectorKeyframeTrack(`.bones[${bone.name}].position`,[0,1],[...bone.position.toArray(),...bone.position.toArray()]));
    }
    tracks.push(new THREE.VectorKeyframeTrack('.bones[センター].position',[0,1],[...center.position.toArray(),...center.position.toArray()]));
    const result=new THREE.AnimationClip('side_lying',1,tracks);
    if(!result.validate()||tracks.some(track=>Array.from(track.values).some(value=>!Number.isFinite(value))))
      throw new Error('侧躺骨骼数据无效，已保留原来的姿态');
    result.userData={source:'Female Laying Pose',sourceDuration:clip.duration,scale,mappedBones:tracked.length,costumeAdaptation:'shallow_knee',frozenDynamicBones:dynamic.size};
    return result;
  }finally{
    mixer.stopAllAction();mixer.uncacheRoot(asset);
    saved.forEach((value,b)=>{b.position.copy(value.position);b.quaternion.copy(value.rotation);});update();
  }
}
