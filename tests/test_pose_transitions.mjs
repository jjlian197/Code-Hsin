import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {MMDAnimationHelper} from '../src/assets/pmx_viewer/lib/three/addons/animation/MMDAnimationHelper.js';
import {createBuiltinClips} from '../src/assets/pmx_viewer/motions.js';
import {HsinBehavior} from '../src/assets/pmx_viewer/behavior.js';
import {transitionAssets} from '../src/assets/pmx_viewer/pose_transitions.js';
import {PoseCloth} from '../src/assets/pmx_viewer/pose_cloth.js';
globalThis.window={Ammo:null};
const {AnimationRuntime}=await import('../src/assets/pmx_viewer/animation_runtime.js');
const config=JSON.parse(execFileSync('python',['-c','import json;from src.core.app_config import load_config,project_path;print(json.dumps({n:str(project_path(p)) for n,p in load_config()["sprite"]["model"]["forms"].items()}))'],{encoding:'utf8'}));
for(const [form,path] of Object.entries(config)){
  const file=`motions/hsin/${form}.json`;
  if(!fs.existsSync(path)||!fs.existsSync(file)){console.log('SKIP: local calibration required',form);continue;}
  const raw=JSON.parse(fs.readFileSync(file)),bytes=fs.readFileSync(path);
  const data=new Parser().parsePmx(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),true);
  const mesh=new THREE.SkinnedMesh(),bones=data.bones.map(b=>{
    const node=new THREE.Bone();node.name=b.name;node.position.fromArray(b.position);
    if(b.parentIndex>=0)node.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return node;
  });
  bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));mesh.bind(new THREE.Skeleton(bones));
  mesh.geometry.userData.MMD={rigidBodies:[],iks:[],grants:[]};mesh.morphTargetDictionary={};mesh.morphTargetInfluences=[];
  const assets=transitionAssets(raw,raw.model_sha256,mesh);
  assert.throws(()=>transitionAssets(raw,'another-model',mesh),/不匹配/);
  const invalid=structuredClone(raw);invalid.clips.lie_down.tracks[0].values[1]=NaN;
  assert.throws(()=>transitionAssets(invalid,raw.model_sha256,mesh),/无效/);
  for(const [name,clip] of Object.entries(assets.clips)){
    assert(clip.validate());
    const initial=name==='get_up'?raw.lying:name==='side_lying'?raw.lying:raw.standing;
    const final=name==='get_up'?raw.standing:raw.lying;
    for(const [bone,pose] of Object.entries(initial))for(const [property,type] of [['q','quaternion'],['p','position']]){
      const track=clip.tracks.find(t=>t.name===`.bones[${bone}].${type}`);
      assert(track);const size=track.getValueSize();
      assert(track.values.slice(0,size).every((value,i)=>Math.abs(value-pose[property][i])<2e-5),name+' initial '+bone);
      assert(track.values.slice(-size).every((value,i)=>Math.abs(value-final[bone][property][i])<2e-5),name+' final '+bone);
    }
    for(const track of clip.tracks.filter(t=>t.ValueTypeName==='quaternion')){
      for(let i=4;i<track.values.length;i+=4)assert(new THREE.Quaternion().fromArray(track.values,i-4).angleTo(new THREE.Quaternion().fromArray(track.values,i))<.38,track.name+' discontinuity');
    }
  }
  for(const source of Object.values(raw.clips))for(const key of ['right_ankle','left_ankle']){
    const points=source.contacts.filter(c=>c.feet).map(c=>c[key]);
    assert(points.length>10,'foot support phase is present');
    for(const axis of [0,2])assert(Math.max(...points.map(p=>p[axis]))-Math.min(...points.map(p=>p[axis]))<.02,'planted foot horizontal drift');
  }
  const neck=assets.clips.lie_down.tracks.find(t=>t.name==='.bones[首].quaternion');
  const neckEuler=new THREE.Euler().setFromQuaternion(new THREE.Quaternion().fromArray(neck.createInterpolant().evaluate(.8)));
  assert(Math.abs(neckEuler.z)<13*Math.PI/180,'neutral ASF axes must not twist the neck at entry');
  assert(new THREE.Quaternion().fromArray(neck.createInterpolant().evaluate(.8)).angleTo(new THREE.Quaternion())<.08,'standing source reference is neutral');
  const clips=createBuiltinClips(mesh),helper=new MMDAnimationHelper({sync:false});helper.add(mesh,{animation:clips.idle,physics:false});
  const runtime=Object.assign(Object.create(AnimationRuntime.prototype),{
    mesh,helper,clips,mixer:helper.objects.get(mesh).mixer,
    bindPose:bones.map(b=>({position:b.position.clone(),rotation:b.quaternion.clone()})),
    behavior:new HsinBehavior(mesh,{breathing:false,mouse_follow:false,random_idle:false}),
    physics:{reset(){}},physicsEnabled:false,transitions:assets,poseProfile:null,activeAction:null,finishedAction:null,
    motion:'idle',motionGeneration:0,pendingCommand:null,pendingSide:false,paused:false,frames:0,steps:0,elapsed:0,
    poseCache:new Map(),maskedIdleCache:new Map(),vmdCache:new Map()
  });
  runtime.baseAction=runtime.mixer.clipAction(clips.idle);runtime.evaluatePose();
  runtime.mixer.addEventListener('finished',e=>{if(e.action===runtime.activeAction)runtime.finishedAction=e.action;});
  const advance=seconds=>{for(let i=0;i<Math.ceil(seconds*30);i++)runtime.update(1/30);};
  const assertIdleArms=()=>{
    for(const name of ['右腕','左腕']){
      const idleTrack=clips.idle.tracks.find(t=>t.name===`.bones[${name}].quaternion`);
      assert(bones.find(b=>b.name===name).quaternion.angleTo(new THREE.Quaternion().fromArray(idleTrack.values))<.02,name+' must return to arms-down idle');
    }
  };
  await runtime.loadSideLying('unused');advance(2);assert.equal(runtime.motion,'lie_down');
  const elapsed=runtime.activeAction.time;await runtime.loadSideLying('unused');assert.equal(runtime.activeAction.time,elapsed);
  runtime.play('wave');runtime.play('idle');advance(6);assert.equal(runtime.motion,'get_up');advance(8);assert.equal(runtime.motion,'idle');assertIdleArms();
  await runtime.loadSideLying('unused');advance(8);assert.equal(runtime.motion,'side_lying');runtime.play('wave');advance(8);assert.equal(runtime.motion,'wave');advance(4);
  for(let i=0;i<4;i++){await runtime.loadSideLying('unused');advance(8);runtime.play('idle');advance(8);assertIdleArms();advance(2);assertIdleArms();}
  assert(runtime.mixer._actions.length<12,'temporary masks and blends must be released');
  assert(bones.find(b=>b.name==='センター').quaternion.angleTo(new THREE.Quaternion())<1e-5);
  mesh.geometry.userData.MMD.rigidBodies=data.rigidBodies;
  mesh.geometry.userData.MMD.constraints=data.constraints;
  runtime.poseCloth=new PoseCloth(mesh,assets.floor);runtime.physicsEnabled=true;
  await runtime.loadSideLying('unused');advance(10);
  assert.equal(runtime.motion,'side_lying');
  const cloth=runtime.poseCloth.snapshot();
  assert(cloth.particles>500&&cloth.links>400&&cloth.steps>250,'actual PMX cloth topology is simulated');
  assert(cloth.max_displacement>.05&&cloth.min_free_y>=assets.floor+.064,'cloth sags and collides with ground');
  for(const n of runtime.poseCloth.nodes)assert([...n.bone.position.toArray(),...n.bone.quaternion.toArray()].every(Number.isFinite),'finite cloth transform');
  runtime.setPhysics(false);advance(1);assert.equal(runtime.poseCloth.active,false);
  runtime.setPhysics(true);advance(3);assert.equal(runtime.poseCloth.active,true);
  runtime.play('idle');advance(8);assertIdleArms();assert.equal(runtime.poseCloth.active,false);
  helper.remove(mesh);runtime.mixer.stopAllAction();runtime.mixer.uncacheRoot(mesh);
  console.log('PASS:',form,'endpoints, smooth frames, invalid assets, safe queue, real helper backups, repeated playback cache');
}
