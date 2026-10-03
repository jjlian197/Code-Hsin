import assert from 'node:assert/strict';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {MMDAnimationHelper} from '../src/assets/pmx_viewer/lib/three/addons/animation/MMDAnimationHelper.js';
import {createBuiltinClips} from '../src/assets/pmx_viewer/motions.js';
import {HsinBehavior} from '../src/assets/pmx_viewer/behavior.js';
import {classifyTouch, reactToTouch} from '../src/assets/pmx_viewer/interaction.js';
globalThis.window={Ammo:null};
const {AnimationRuntime}=await import('../src/assets/pmx_viewer/animation_runtime.js');
const paths=JSON.parse(execFileSync('python',['-X','utf8','-c','import json; from src.core.app_config import load_config,project_path; print(json.dumps([str(project_path(p)) for p in load_config()["sprite"]["model"]["forms"].values()]))'],{encoding:'utf8'}));

for(const path of paths){
  const raw=fs.readFileSync(path),data=new Parser().parsePmx(raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),true);
  const mesh=new THREE.SkinnedMesh(),bones=data.bones.map(b=>{const bone=new THREE.Bone();bone.name=b.name;bone.position.fromArray(b.position);
    if(b.parentIndex>=0)bone.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return bone;});
  bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));
  mesh.bind(new THREE.Skeleton(bones));mesh.updateMatrixWorld(true);
  mesh.morphTargetDictionary={};mesh.morphTargetInfluences=[];mesh.geometry.userData.MMD={iks:[],grants:[]};
  const bind=bones.map(b=>({position:b.position.clone(),rotation:b.quaternion.clone()}));
  const clips=createBuiltinClips(mesh);
  assert(bones.every((b,i)=>b.position.equals(bind[i].position)&&b.quaternion.equals(bind[i].rotation)),'构建不改变现场骨骼');
  const helper=new MMDAnimationHelper({sync:false});helper.add(mesh,{animation:clips.idle,physics:false});
  const runtime=Object.assign(Object.create(AnimationRuntime.prototype),{mesh,helper,clips,mixer:helper.objects.get(mesh).mixer,
    bindPose:bind,behavior:new HsinBehavior(mesh,{auto_blink:false,breathing:false,mouse_follow:false,random_idle:false}),
    physics:{reset(){}},physicsEnabled:false,poseProfile:null,activeAction:null,finishedAction:null,gestureRelease:null,
    motion:'idle',motionGeneration:0,maskedIdleCache:new Map(),frames:0,elapsed:0});
  runtime.baseAction=runtime.mixer.clipAction(clips.idle);
  runtime.mixer.addEventListener('finished',e=>{if(e.action===runtime.activeAction)runtime.finishedAction=e.action;});
  runtime.evaluatePose();
  const owned=new Set(clips.finger_heart.tracks.map(t=>t.name.match(/\.bones\[(.+)\]/)[1]));
  const lower=bones.filter(b=>/^(全ての親|センター|グルーブ|腰|下半身|[左右](足|ひざ|つま先))/.test(b.name));
  const lowerRest=lower.map(b=>({q:b.quaternion.clone(),p:b.position.clone()}));
  for(const clip of [clips.finger_heart,clips.crossed_arms]){
    assert(clip.tracks.every(t=>owned.has(t.name.match(/\.bones\[(.+)\]/)[1])),'仅拥有头颈和手臂，不接管下半身');
    assert(clip.tracks.every(t=>[...t.values].every(Number.isFinite)));
    for(const track of clip.tracks)for(let i=4;i<track.values.length;i+=4){
      assert(new THREE.Quaternion().fromArray(track.values,i-4).angleTo(new THREE.Quaternion().fromArray(track.values,i))<.17,'进入退出采样无大跳变');
    }
  }
  for(const motion of ['finger_heart','crossed_arms']){
    runtime.play(motion);for(let i=0;i<60;i++)runtime.update(1/30);
    const time=runtime.activeAction.time, generation=runtime.motionGeneration;
    runtime.play(motion);
    assert.equal(runtime.activeAction.time,time,'重复触发不重新计时');assert.equal(runtime.motionGeneration,generation);
    for(const next of ['idle','nod','crossed_arms']){
      if(next===motion)continue;
      const before=new Map(bones.filter(b=>owned.has(b.name)).map(b=>[b,b.quaternion.clone()]));
      runtime.play(next);
      // Float32 关键帧可能有微小模长误差；测朝向差之前先归一化，不能把它误报成跳姿。
      const jumps=[...before].map(([b,q])=>({name:b.name,angle:b.quaternion.clone().normalize().angleTo(q.clone().normalize())})).filter(x=>x.angle>2e-5);
      assert(!jumps.length,`中断首帧保持当帧姿势 ${motion} → ${next}: ${JSON.stringify(jumps)}`);
      assert(runtime.gestureRelease,'中断有短暂退出过渡');
      for(let i=0;i<15;i++)runtime.update(1/30);
      assert(!runtime.gestureRelease,'释放过渡完成并清理');
      runtime.play('idle');for(let i=0;i<15;i++)runtime.update(1/30);
      for(const side of ['右','左'])assert(Math.abs(bones.find(b=>b.name===side+'腕').rotation.z-(side==='右'?.67:-.67))<1e-5);
      runtime.play(motion);for(let i=0;i<60;i++)runtime.update(1/30);
    }
    for(let i=0;i<200;i++)runtime.update(1/30);
    assert.equal(runtime.motion,'idle');assert(!runtime.behavior.manualMotion,'完成后自动恢复行为');
    assert(bones.filter(b=>/^[左右].*指[０１２３]$/.test(b.name)).every(b=>b.quaternion.angleTo(new THREE.Quaternion())<1e-5),'释放全部弯指');
    assert(lower.every((b,i)=>b.position.distanceTo(lowerRest[i].p)<1e-5&&b.quaternion.clone().normalize().angleTo(lowerRest[i].q.clone().normalize())<1e-5),'下半身保持（允许 helper Float32 备份精度）');
  }
  const point=name=>bones.find(b=>b.name===name).getWorldPosition(new THREE.Vector3());
  const chest=point('上半身2');
  assert.equal(classifyTouch(mesh,{point:chest.clone().add(new THREE.Vector3(0,1.25,2))}),'chest');
  assert.equal(classifyTouch(mesh,{point:chest.clone().add(new THREE.Vector3(0,-1.5,1))}),'body');
  assert.equal(classifyTouch(mesh,{point:point('頭').add(new THREE.Vector3(0,.4,1))}),'head');
  assert.equal(classifyTouch(mesh,{point:point('右手首')}),'hand');
  const tail=data.vertices.find(v=>v.skinIndices.some((bi,j)=>v.skinWeights[j]>.25&&/^Tail_|尾|しっぽ/i.test(bones[bi].name)));
  assert(tail,'真实 PMX 有带尾巴权重的顶点');
  mesh.geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute([...tail.skinIndices,0,0,0,0].slice(0,4),4));
  mesh.geometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute([...tail.skinWeights,0,0,0,0].slice(0,4),4));
  assert.equal(classifyTouch(mesh,{point:point('頭'),face:{a:0,b:0,c:0}}),'tail','真实尾巴蒙皮优先于屏幕/高度区域');
  for(const [part,motion] of [['head','finger_heart'],['chest','crossed_arms'],['hand','peace'],['body','wave']]){
    runtime.play('idle');for(let i=0;i<20;i++)runtime.update(1/30);
    assert(reactToTouch(runtime,part));assert.equal(runtime.motion,motion);
    assert(!reactToTouch(runtime,part),'冷却期不重复触发');
    for(let i=0;i<180;i++)runtime.update(1/30);
    assert.equal(runtime.motion,'idle');
  }
  assert(reactToTouch(runtime,'tail',-1));
  for(let i=0;i<27;i++)runtime.update(1/30);
  assert(bones.find(b=>b.name==='頭').rotation.y<-.4,'尾巴反应向触摸侧转头');
  for(let i=0;i<60;i++)runtime.update(1/30);
  assert(Math.abs(bones.find(b=>b.name==='頭').rotation.y)<1e-5,'尾巴回头自动释放');
  runtime.behavior.setSettings({touch_reactions:false});
  assert(!reactToTouch(runtime,'head'));assert.equal(runtime.motion,'idle');
  runtime.behavior.setSettings({touch_reactions:true});
  runtime.poseProfile='stable_side';runtime.motion='side_lying';
  assert(reactToTouch(runtime,'chest'));assert.equal(runtime.motion,'side_lying','侧躺不会被触摸强制站起');
  for(let i=0;i<20;i++)runtime.update(1/30);
  runtime.poseProfile=null;runtime.motion='external_vmd';
  assert(reactToTouch(runtime,'head'));assert.equal(runtime.motion,'external_vmd','外部动作保留控制权');
  helper.remove(mesh);runtime.mixer.stopAllAction();runtime.mixer.uncacheRoot(mesh);
}
console.log('PASS: both forms, gesture continuity, repeat suppression, smooth interruption, cleanup, fingers and lower-body isolation');
