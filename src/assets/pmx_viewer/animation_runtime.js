import * as THREE from 'three';
import { MMDAnimationHelper } from 'three/addons/animation/MMDAnimationHelper.js';
import { MMDLoader } from 'three/addons/loaders/MMDLoader.js';
import { createBuiltinClips, palmNormal } from './motions.js';
import { HsinBehavior } from './behavior.js';
import { loadLayingPose } from './laying_pose.js';
import {blendFromCurrent} from './pose_transitions.js';
import {setGroundSupport} from './ground_support.js';
import {PoseCloth} from './pose_cloth.js';
import {adaptChestPhysics} from './physics_compat.js';

// 每个模型使用独立的 Ammo arena。切换时释放整个 arena 的引用，避免
// 官方 MMDPhysics 缺少销毁接口导致刚体在同一 WASM heap 中累积。
const createAmmo = window.Ammo;
let wasmBytes;
export async function createPhysicsModule() {
  wasmBytes ??= fetch(new URL('./lib/three/addons/libs/ammo.wasm.wasm', import.meta.url))
    .then(response => { if (!response.ok) throw new Error('物理组件无法读取'); return response.arrayBuffer(); });
  return createAmmo({ wasmBinary: await wasmBytes });
}

export class AnimationRuntime {
  constructor(mesh, ammo, options = {}) {
    this.mesh = mesh;
    this.ammo = ammo;
    window.Ammo = ammo;
    this.bindPose = mesh.skeleton.bones.map(b=>({position:b.position.clone(),rotation:b.quaternion.clone()}));
    this.clips = createBuiltinClips(mesh);
    this.helper = new MMDAnimationHelper({ sync: false, resetPhysicsOnLoop: false });
    this.helper.onBeforePhysics = model => { this.behavior?.applyBones(); model.updateMatrixWorld(true); };
    adaptChestPhysics(mesh);
    this.helper.add(mesh, { animation: this.clips.idle, physics: true,
      unitStep: 1 / 65, maxStepNum: 3, warmup: 30 });
    const objects = this.helper.objects.get(mesh);
    this.mixer = objects.mixer;
    this.baseAction = this.mixer.clipAction(this.clips.idle);
    this.vmdCache = new Map();
    this.maskedIdleCache = new Map();
    this.motionGeneration = 0;
    this.physics = objects.physics;
    // 原组件强制每帧至少推进一步；高刷新率下会使衣发物理快于动画。
    // 交给 Bullet 累积真实时间，以固定步长求解。
    this.physics._stepSimulation = delta => this.physics.world.stepSimulation(
      delta, this.physics.maxStepNum, this.physics.unitStep);
    this.physicsIdleTime = 0;
    this.physicsMotionGeneration = this.motionGeneration;
    this.physicsGaze = {x: 0, y: 0};
    this.activeAction = null;
    this.gestureRelease = null;
    this.finishedAction = null;
    this.motion = 'idle';
    this.poseProfile = null;
    this.poseCache = new Map();
    this.transitions=options.transitions||null;
    this.poseCloth=this.transitions?new PoseCloth(mesh,this.transitions.floor):null;
    this.transitionError=options.transition_error||null;
    this.pendingCommand=null;
    this.pendingSide=false;
    this.physicsEnabled = options.physics !== false;
    this.helper.enable('physics', this.physicsEnabled);
    this.frames = this.steps = this.elapsed = 0;
    this.paused = false;
    this.dynamicBodies = this.physics.bodies.filter(b => b.params.type > 0 && b.params.boneIndex >= 0);
    this.restRotations = this.dynamicBodies.map(b => b.bone.quaternion.clone());
    this.behavior = new HsinBehavior(mesh,options.behavior);
    this.behavior.setActivity(options.activity||{state:'idle'});
    this.mixer.addEventListener('finished', event => {
      if (event.action !== this.activeAction) return;
      // finished 在 mixer 正在遍历绑定时触发；延后处理，避免恢复绑定原姿态。
      this.finishedAction = event.action;
    });
  }

  play(group) {
    if (!(group in this.clips)) throw new Error('未知动作');
    if(this.transitions&&this.poseProfile){this.requestStanding({group});return;}
    const calibrated = name => name==='finger_heart'||name==='crossed_arms';
    if(calibrated(group)&&this.motion===group&&this.activeAction?.isRunning())return;
    const leavingPose=!!this.poseProfile;
    this.behavior.prepareFrame();
    // 手势中断时留下当前局部增量，短暂淡出；新动作从自身首帧进入，不先跳回待机。
    const releaseNames=(calibrated(this.motion)||this.gestureRelease)?this.clips.finger_heart.tracks.map(t=>t.name):[];
    const releaseTracks=releaseNames.map(name=>{
      const boneName=name.match(/\.bones\[(.+)\]/)[1];
      const index=this.mesh.skeleton.bones.findIndex(b=>b.name===boneName),bone=this.mesh.skeleton.bones[index];
      const idleTrack=this.clips.idle.tracks.find(t=>t.name===name);
      const base=idleTrack?new THREE.Quaternion().fromArray(idleTrack.values):this.bindPose[index].rotation.clone();
      const delta=base.invert().multiply(bone.quaternion).normalize();
      return new THREE.QuaternionKeyframeTrack(name,[0,.3],[...delta.toArray(),0,0,0,1]);
    });
    this.stopGestureRelease();
    this.restoreIdle();
    if (this.activeAction) this.activeAction.stop();
    this.motionGeneration++;
    this.activeAction = null;
    this.finishedAction = null;
    this.motion = group;
    this.poseProfile = null;
    this.helper.enable('ik',true);
    this.helper.enable('physics',this.physicsEnabled);
    if (group !== 'idle') {
      this.activeAction = this.mixer.clipAction(this.clips[group]);
      this.activeAction.reset().setLoop(THREE.LoopOnce, 1).play();
    }
    if(releaseTracks.length){
      const releaseClip=new THREE.AnimationClip('gesture_release',.3,releaseTracks);
      releaseClip.blendMode=THREE.AdditiveAnimationBlendMode;
      this.gestureRelease=this.mixer.clipAction(releaseClip).setLoop(THREE.LoopOnce,1).play();
    }
    this.refreshMotionOwnership();
    if(leavingPose)this.restoreBindPose();
    this.evaluatePose();
    if(leavingPose)this.physics.reset();
  }

  async loadSideLying(url) {
    if(this.transitionError)throw new Error(this.transitionError);
    if(this.transitions){
      this.pendingCommand=null;
      if(this.motion==='get_up'){this.pendingSide=true;return;}
      this.pendingSide=false;
      if(this.motion==='lie_down'||this.motion==='side_lying')return;
      this.startPoseAction('lie_down',true);return;
    }
    const target=this.mesh,request=++this.motionGeneration;
    if(!this.poseCache.has(url))this.poseCache.set(url,loadLayingPose(url,target));
    let clip;
    try {clip=await this.poseCache.get(url);}catch(error){this.poseCache?.delete(url);if(this.mesh&&request===this.motionGeneration)throw error;return;}
    if(!this.mesh||request!==this.motionGeneration)return;
    this.stopGestureRelease();
    const affected=new Set(clip.tracks.map(track=>track.name));
    const previousBase=this.baseAction,previousAction=this.activeAction;
    const cacheKey='side:'+url;
    if(!this.maskedIdleCache.has(cacheKey))this.maskedIdleCache.set(cacheKey,new THREE.AnimationClip('idle:side_lying',4,this.clips.idle.tracks.filter(t=>!affected.has(t.name))));
    const masked=this.maskedIdleCache.get(cacheKey);
    this.baseAction=this.mixer.clipAction(masked).reset().play();
    this.activeAction=this.mixer.clipAction(clip).reset().setLoop(THREE.LoopRepeat,Infinity).play();
    if(previousBase!==this.baseAction)previousBase.stop();
    if(previousAction&&previousAction!==this.activeAction)previousAction.stop();
    this.finishedAction=null;this.motion='side_lying';this.poseProfile='stable_side';
    this.behavior.setMotionClip(clip);this.behavior.setManualMotion(true);
    this.helper.enable('ik',false);
    this.helper.enable('physics',false);
    this.evaluatePose();
    this.physics.reset();
  }

  requestStanding(command) {
    this.pendingCommand=command;this.pendingSide=false;
    if(this.motion==='side_lying')this.startPoseAction('get_up');
    // 中途要求站立时完成当前支撑段，再播放独立起身；不倒放、不瞬移。
  }

  startPoseAction(name, enter=false) {
    const continuing=!!this.poseProfile;
    this.behavior.prepareFrame();this.stopGestureRelease();
    let clip=this.transitions.clips[name];
    if(enter)clip=blendFromCurrent(clip,this.mesh);
    const affected=new Set(clip.tracks.map(t=>t.name));
    const masked=new THREE.AnimationClip('idle:transition',4,this.clips.idle.tracks.filter(t=>!affected.has(t.name)));
    const previousBase=this.baseAction,previousAction=this.activeAction;
    this.baseAction=this.mixer.clipAction(masked).reset().play();
    this.activeAction=this.mixer.clipAction(clip).reset().setLoop(name==='side_lying'?THREE.LoopRepeat:THREE.LoopOnce,name==='side_lying'?Infinity:1).play();
    this.activeAction.clampWhenFinished=true;
    if(previousBase!==this.baseAction)previousBase.stop();
    if(previousAction&&previousAction!==this.activeAction)previousAction.stop();
    // 动态起点与遮罩属于本次播放，切换后释放，避免重复往返积累 mixer 缓存。
    if(this.poseTemporary){for(const c of this.poseTemporary)this.mixer.uncacheClip(c);}
    this.poseTemporary=[masked,...(enter?[clip]:[])];
    this.finishedAction=null;this.motionGeneration++;
    this.motion=name;this.poseProfile=name==='side_lying'?'stable_side':'ground_transition';
    this.helper.enable('ik',false);this.helper.enable('physics',false);
    this.refreshMotionOwnership();setGroundSupport(this.mesh,this.transitions.floor,true);
    this.evaluatePose();this.physics.reset();
    if(!continuing)this.poseCloth?.reset();
  }

  finishPoseAction() {
    if(this.motion==='lie_down'){
      this.startPoseAction('side_lying');
      if(this.pendingCommand)this.startPoseAction('get_up');
      return;
    }
    const pending=this.pendingCommand||{group:'idle'},side=this.pendingSide;
    this.pendingCommand=null;this.pendingSide=false;
    this.poseProfile=null;setGroundSupport(this.mesh,this.transitions.floor,false);
    this.poseCloth?.stop();
    this.restoreIdle();this.activeAction.stop();this.activeAction=this.finishedAction=null;
    if(this.poseTemporary){for(const c of this.poseTemporary)this.mixer.uncacheClip(c);this.poseTemporary=null;}
    this.restoreBindPose();this.motion='idle';this.helper.enable('ik',true);
    this.refreshMotionOwnership();this.evaluatePose();this.physics.reset();
    if(side)this.startPoseAction('lie_down',true);
    else if(pending.url)this.loadVmd(pending.url,pending.group).catch(error=>{this.asyncMotionError=String(error.message||error);});
    else if(pending.group!=='idle')this.play(pending.group);
  }

  restoreIdle() {
    if (this.baseAction.getClip() === this.clips.idle) return;
    const previous = this.baseAction;
    // 先激活新的待机绑定，再解除旧动作；共有骨骼不会暂时恢复 T pose。
    this.baseAction = this.mixer.clipAction(this.clips.idle).reset().play();
    previous.stop();
  }

  stopGestureRelease() {
    if(!this.gestureRelease)return;
    const clip=this.gestureRelease.getClip();
    this.gestureRelease.stop();this.mixer.uncacheAction(clip,this.mesh);this.gestureRelease=null;
  }

  refreshMotionOwnership() {
    const clip=this.activeAction?.getClip()||null;
    this.behavior.setMotionClip(this.gestureRelease?new THREE.AnimationClip('gesture_owned',1,
      [...(clip?.tracks||[]),...this.gestureRelease.getClip().tracks]):clip);
    this.behavior.setManualMotion(this.motion!=='idle'||!!this.gestureRelease);
  }

  restoreBindPose() {
    // 停止侧躺 action 只解除 mixer 绑定；MMDHelper 下一帧仍会恢复侧躺的骨骼备份。
    // 同时重置真实骨骼和 helper 的动画前备份，再让待机/新动作、IK 与物理重新求值。
    const backup=this.helper.objects.get(this.mesh).backupBones;
    this.mesh.skeleton.bones.forEach((bone,i)=>{
      bone.position.copy(this.bindPose[i].position);
      bone.quaternion.copy(this.bindPose[i].rotation);
    });
    // 常量待机轨道的 mixer 缓存可能仍是下垂姿势，手动归零后不会再次写入。
    // 明确恢复当前待机值，绑定姿势仍保留给重定向使用。
    for(const track of this.clips.idle.tracks){
      const match=track.name.match(/^\.bones\[(.+)\]\.(quaternion|position)$/);
      const bone=match&&this.mesh.skeleton.bones.find(b=>b.name===match[1]);
      if(bone)bone[match[2]].fromArray(track.createInterpolant().evaluate(this.baseAction.time||0));
    }
    if(backup)this.mesh.skeleton.bones.forEach((bone,i)=>{
      bone.position.toArray(backup,i*7);bone.quaternion.toArray(backup,i*7+3);
    });
  }

  evaluatePose() {
    this.behavior.prepareFrame();
    this.helper.enable('physics', false);
    this.helper.update(0);
    this.behavior.applyBones();
    this.behavior.applyFace();
    this.mesh.updateMatrixWorld(true);
    this.helper.enable('physics', this.physicsEnabled && !this.poseProfile);
  }

  async loadVmd(url, name) {
    if(this.transitions&&this.poseProfile){this.requestStanding({group:name,url});return;}
    const target = this.mesh;
    const request = ++this.motionGeneration;
    if (!this.vmdCache.has(url)) {
      this.vmdCache.set(url, new Promise((resolve, reject) =>
        new MMDLoader().loadAnimation(url, target, resolve, undefined, reject)));
    }
    let clip;
    try { clip = await this.vmdCache.get(url); }
    catch (error) {
      if (!this.mesh || request !== this.motionGeneration) return;
      this.vmdCache.delete(url); throw error;
    }
    if (!this.mesh || request !== this.motionGeneration) return;
    if (!clip.tracks.length || !clip.validate() || clip.tracks.some(track =>
      track.getValueSize() !== (track.ValueTypeName === 'quaternion' ? 4 : track.ValueTypeName === 'vector' ? 3 : 1))) {
      throw new Error('VMD 没有适用的有效关键帧');
    }
    // VMD 没有写到的骨骼继续使用待机，避免局部动作让两臂跳回 A pose。
    if (!this.maskedIdleCache.has(url)) {
      const affected = new Set(clip.tracks.map(track => track.name));
      this.maskedIdleCache.set(url, new THREE.AnimationClip(`idle:${name}`, 4,
        this.clips.idle.tracks.filter(track => !affected.has(track.name))));
    }
    const idle = this.maskedIdleCache.get(url);
    this.stopGestureRelease();
    const leavingPose=!!this.poseProfile;
    this.poseProfile=null;this.helper.enable('ik',true);
    const previousBase = this.baseAction, previousAction = this.activeAction;
    this.baseAction = this.mixer.clipAction(idle).reset().play();
    this.activeAction = this.mixer.clipAction(clip);
    this.activeAction.reset().setLoop(THREE.LoopOnce, 1).play();
    if (previousBase !== this.baseAction) previousBase.stop();
    if (previousAction && previousAction !== this.activeAction) previousAction.stop();
    this.finishedAction = null;
    this.motion = name;
    this.behavior.setMotionClip(clip);
    this.behavior.setManualMotion(true);
    this.behavior.prepareFrame();
    if(leavingPose)this.restoreBindPose();
    this.helper.enable('physics', false);
    this.helper.update(0);
    this.physics.reset();
    this.helper.enable('physics', this.physicsEnabled);
  }

  setPhysics(enabled) {
    this.physicsIdleTime = 0;
    this.physicsRestPose = null;
    this.physicsEnabled = enabled;
    this.helper.enable('physics', enabled && !this.poseProfile);
    if(this.poseProfile){this.poseCloth?.stop();}
    else if (enabled) this.physics.reset();
  }

  resetPhysics() {
    this.physicsIdleTime = 0;
    this.physicsRestPose = null;
    const enabled = this.physicsEnabled;
    this.helper.enable('physics', false);
    this.behavior.prepareFrame();
    this.helper.update(0);
    this.physics.reset();
    if(this.poseProfile)this.poseCloth?.reset();
    if(!this.poseProfile)this.physics.warmup(30);
    this.helper.enable('physics', enabled && !this.poseProfile);
  }

  update(delta) {
    if (this.paused || !this.mesh) return;
    const realDelta = delta;
    delta = Math.min(delta, 0.05);
    this.behavior.prepareFrame();
    // 物理仍限制步长；自然反应按实时时间结束，低帧率不延长口型与触摸。
    this.behavior.advance(realDelta);
    let restingPhysics = false;
    if (this.physicsEnabled && !this.poseProfile) {
      const gaze = this.behavior.gaze;
      const moving = this.motion !== 'idle' || this.gestureRelease || this.behavior.touchState
        || this.behavior.idleAction || this.behavior.activity.state !== 'idle'
        || this.behavior.activity.interacting || this.physicsMotionGeneration !== this.motionGeneration
        || Math.hypot(gaze.x - this.physicsGaze.x, gaze.y - this.physicsGaze.y) > 0.002;
      this.physicsMotionGeneration = this.motionGeneration;
      this.physicsGaze = {...gaze};
      this.physicsIdleTime = moving ? 0 : this.physicsIdleTime + delta;
      restingPhysics = this.physicsIdleTime >= 3;
      // 密集 PMX 碰撞在静止身体上仍会激发微振；静息后保留衣发姿态，互动时恢复。
      if (restingPhysics && !this.physicsRestPose) this.physicsRestPose = this.dynamicBodies.map(b => ({
        bone: b.bone, position: b.bone.position.clone(), rotation: b.bone.quaternion.clone(),
      }));
      if (!restingPhysics) this.physicsRestPose = null;
      this.helper.enable('physics', !restingPhysics);
    }
    this.helper.update(delta);
    if (restingPhysics) for (const pose of this.physicsRestPose) {
      pose.bone.position.copy(pose.position);
      pose.bone.quaternion.copy(pose.rotation);
    }
    if(this.gestureRelease&&!this.gestureRelease.isRunning()){
      this.stopGestureRelease();this.refreshMotionOwnership();
    }
    if (this.finishedAction === this.activeAction && this.finishedAction) {
      if(this.transitions&&this.poseProfile){this.finishPoseAction();}
      else {
      this.restoreIdle();
      this.activeAction.stop();
      this.activeAction = this.finishedAction = null;
      this.motion = 'idle';
      this.behavior.setMotionClip(null);
      this.behavior.setManualMotion(false);
      this.evaluatePose();
      }
    }
    else {
      if(!this.physicsEnabled||this.poseProfile)this.behavior.applyBones();
      this.behavior.applyFace();
    }
    this.mesh.updateMatrixWorld(true);
    if(this.poseProfile&&this.physicsEnabled&&this.poseCloth){
      const remaining=this.motion==='get_up'?this.activeAction.getClip().duration-this.activeAction.time:1;
      this.poseCloth.update(delta,THREE.MathUtils.smoothstep(remaining,0,.6));
      this.mesh.updateMatrixWorld(true);
    }
    this.frames++;
    this.elapsed += delta;
    if (this.physicsEnabled && !restingPhysics) this.steps++;
  }

  snapshot() {
    let motionAngle = 0;
    this.dynamicBodies.forEach((b, i) => {
      motionAngle = Math.max(motionAngle, b.bone.quaternion.angleTo(this.restRotations[i]));
    });
    return { motion: this.motion, physics_enabled: this.physicsEnabled,
      posture_state:this.motion==='lie_down'||this.motion==='get_up'||this.motion==='side_lying'?this.motion:'standing',
      transition_available:!!this.transitions,transition_error:this.transitionError,
      transition_duration:this.poseProfile?this.activeAction?.getClip().duration:null,
      queued_motion:this.pendingSide?'side_lying':this.pendingCommand?.group||null,
      floor_y:this.transitions?.floor??null,motion_error:this.asyncMotionError||null,
      physics_active:this.physicsEnabled&&(!this.poseProfile?!this.physicsRestPose:!!this.poseCloth),
      physics_resting:this.physicsEnabled&&!this.poseProfile&&!!this.physicsRestPose,pose_profile:this.poseProfile,
      cloth:this.poseCloth?.snapshot()||null,
      engine: this.poseProfile&&this.physicsEnabled?'骨骼布料/PBD':'Ammo/Bullet', rigid_bodies: this.physics.bodies.length,
      constraints: this.physics.constraints.length, dynamic_bones: this.dynamicBodies.length,
      frames: this.frames, physics_steps: this.steps, dynamic_bone_angle: motionAngle,
      motion_time: this.activeAction?.time || 0, animation_time: this.elapsed,
      document_hidden: document.hidden,
      head_rotation: this.mesh.skeleton.bones.find(b => b.name === '頭')?.rotation.toArray().slice(0, 3),
      root_rotation: this.mesh.skeleton.bones.find(b => b.name === 'センター')?.quaternion.toArray(),
      root_position: this.mesh.skeleton.bones.find(b => b.name === 'センター')?.position.toArray(),
      body_positions: Object.fromEntries([['head','頭'],['right_ankle','右足首'],['left_ankle','左足首']].map(([key,name])=>
        [key,this.mesh.skeleton.bones.find(b=>b.name===name)?.getWorldPosition(new THREE.Vector3()).toArray()])),
      torso_position: this.mesh.skeleton.bones.find(b => b.name === '上半身')?.position.toArray(),
      right_arm_rotation: this.mesh.skeleton.bones.find(b => b.name === '右腕')?.rotation.toArray().slice(0, 3),
      left_arm_rotation: this.mesh.skeleton.bones.find(b => b.name === '左腕')?.rotation.toArray().slice(0, 3),
      right_palm_normal: palmNormal(this.mesh)?.toArray(),
      wasm_heap_bytes: this.ammo.HEAP8.length, paused: this.paused,
      behavior:this.behavior.snapshot() };
  }

  dispose() {
    this.stopGestureRelease();
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.mesh);
    this.helper.remove(this.mesh);
    this.mesh = this.helper = this.physics = this.mixer = this.ammo = null;
    this.dynamicBodies = this.restRotations = this.clips = this.activeAction = null;
    this.bindPose = null;
    this.vmdCache.clear(); this.vmdCache = this.baseAction = null;
    this.poseCache.clear();this.poseCache=null;
    this.maskedIdleCache.clear(); this.maskedIdleCache = null;
    this.behavior = null;
    this.poseCloth=null;
    window.Ammo = null;
  }
}
