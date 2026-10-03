import assert from 'node:assert/strict';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import { Parser } from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import { FBXLoader } from '../src/assets/pmx_viewer/lib/three/addons/loaders/FBXLoader.js';
import { retargetLayingPose } from '../src/assets/pmx_viewer/laying_pose.js';
import { MMDAnimationHelper } from '../src/assets/pmx_viewer/lib/three/addons/animation/MMDAnimationHelper.js';
import { createBuiltinClips } from '../src/assets/pmx_viewer/motions.js';
import { HsinBehavior } from '../src/assets/pmx_viewer/behavior.js';
globalThis.window={Ammo:null};
const { AnimationRuntime }=await import('../src/assets/pmx_viewer/animation_runtime.js');

const config=JSON.parse(execFileSync('python',['-c',
  'import json; from src.core.app_config import load_config,project_path; c=load_config(); print(json.dumps({"pose":str(project_path(c["sprite"]["animation"]["side_lying"])),"models":[str(project_path(p)) for p in c["sprite"]["model"]["forms"].values()]}))'],{encoding:'utf8'}));
if(!fs.existsSync(config.pose)){console.log('SKIP: user FBX is not distributed with source');process.exit(0);}
const buffer=path=>{const b=fs.readFileSync(path);return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);};
const source=new FBXLoader().parse(buffer(config.pose),'');
for(const path of config.models){
  const data=new Parser().parsePmx(buffer(path),true),mesh=new THREE.SkinnedMesh();
  const bones=data.bones.map(b=>{const node=new THREE.Bone();node.name=b.name;node.position.fromArray(b.position);
    if(b.parentIndex>=0)node.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return node;});
  bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));
  mesh.bind(new THREE.Skeleton(bones));mesh.geometry.userData.MMD={rigidBodies:data.rigidBodies};
  bones.find(b=>b.name==='右腕').rotation.z=.67;
  const prior=bones.map(b=>[...b.position.toArray(),...b.quaternion.toArray()]);
  const clip=retargetLayingPose(source,mesh);
  assert(clip.validate());
  assert.deepEqual(bones.map(b=>[...b.position.toArray(),...b.quaternion.toArray()]),prior,'retargeting restores the live mesh');
  assert(clip.userData.frozenDynamicBones>600,'bind hair and clothing independently of standing simulation');
  for(const track of clip.tracks){assert([...track.values].every(Number.isFinite));assert.equal(track.values.length,track.times.length*track.getValueSize());}
  const mixer=new THREE.AnimationMixer(mesh);mixer.clipAction(clip).setLoop(THREE.LoopRepeat,Infinity).play();mixer.update(3);
  mesh.updateMatrixWorld(true);
  const position=name=>bones.find(b=>b.name===name).getWorldPosition(new THREE.Vector3());
  const hip=position('下半身'),head=position('頭');
  assert(head.x<hip.x-3,'head beside pelvis instead of upright');
  assert(position('右手首').distanceTo(head)<4,'supporting hand stays near head');
  for(const side of ['右','左']){
    assert(position(side+'足首').x>hip.x+8,'legs extend horizontally along the dress');
    const thigh=position(side+'ひざ').sub(position(side+'足')).normalize();
    const calf=position(side+'足首').sub(position(side+'ひざ')).normalize();
    assert(thigh.dot(calf)>.8,'keep knee bend below 37 degrees for the long skirt');
  }
  const pose=bones.map(b=>b.quaternion.toArray());mixer.update(20);mesh.updateMatrixWorld(true);
  assert.deepEqual(bones.map(b=>b.quaternion.toArray()),pose,'static FBX holds over multiple loops');
  mixer.stopAllAction();mixer.uncacheRoot(mesh);
  assert(bones.every(b=>b.quaternion.toArray().every(Number.isFinite)));
  // 用真实 helper 的骨骼备份和应用的切换路径复现退出问题；离线不运行 Ammo。
  mesh.pose();mesh.morphTargetDictionary={};mesh.morphTargetInfluences=[];
  Object.assign(mesh.geometry.userData.MMD,{iks:[],grants:[]});
  const clips=createBuiltinClips(mesh),helper=new MMDAnimationHelper({sync:false});
  helper.add(mesh,{animation:clips.idle,physics:false});
  const runtime=Object.assign(Object.create(AnimationRuntime.prototype),{
    mesh,helper,clips,mixer:helper.objects.get(mesh).mixer,
    bindPose:bones.map(b=>({position:b.position.clone(),rotation:b.quaternion.clone()})),
    behavior:new HsinBehavior(mesh,{breathing:false,mouse_follow:false,random_idle:false}),
    physics:{reset(){}},physicsEnabled:false,poseProfile:null,activeAction:null,finishedAction:null,
    motionGeneration:0,poseCache:new Map([['local',Promise.resolve(clip)]]),maskedIdleCache:new Map(),vmdCache:new Map()
  });
  runtime.baseAction=runtime.mixer.clipAction(clips.idle);runtime.evaluatePose();
  const assertUpright=()=>{
    const root=bones.find(b=>b.name==='センター');
    assert(root.quaternion.angleTo(new THREE.Quaternion())<1e-5,'center rotation must be upright');
    assert(root.position.distanceTo(runtime.bindPose[bones.indexOf(root)].position)<1e-5,'center position must return to standing');
    assert(position('頭').y>Math.max(position('右足首').y,position('左足首').y)+15,'verify world posture rather than motion name');
  };
  for(const motion of ['idle','nod','wave']){
    await runtime.loadSideLying('local');helper.update(.1);mesh.updateMatrixWorld(true);
    assert(bones.find(b=>b.name==='センター').quaternion.angleTo(new THREE.Quaternion())>1,'enter actual side-lying');
    runtime.play(motion);
    for(let i=0;i<10;i++){runtime.evaluatePose();assertUpright();}
    runtime.play('idle');
  }
  await runtime.loadSideLying('local');helper.update(.1);
  runtime.vmdCache.set('vmd',Promise.resolve(new THREE.AnimationClip('head-vmd',1,[new THREE.QuaternionKeyframeTrack('.bones[頭].quaternion',[0,1],[0,0,0,1,0,0,0,1])])));
  await runtime.loadVmd('vmd','head-vmd');
  for(let i=0;i<10;i++){runtime.evaluatePose();assertUpright();}
  helper.remove(mesh);runtime.mixer.stopAllAction();runtime.mixer.uncacheRoot(mesh);
}
const invalid=new THREE.Group();invalid.animations=[source.animations.find(c=>c.tracks.length>20)];
assert.throws(()=>retargetLayingPose(invalid,null),/缺少 Mixamo/);
invalid.animations=[new THREE.AnimationClip('dance',10,invalid.animations[0].tracks)];
assert.throws(()=>retargetLayingPose(invalid,null),/定格 FBX/);
console.log('PASS: both forms, FBX retargeting, held pose, real MMD helper cache, idle/nod/wave/VMD restore standing');
