import * as THREE from 'three';
import { MMDAnimationHelper } from 'three/addons/animation/MMDAnimationHelper.js';
import { MMDLoader } from 'three/addons/loaders/MMDLoader.js';
import { createBuiltinClips, palmNormal } from './motions.js';
import { HsinBehavior } from './behavior.js';
import { loadLayingPose } from './laying_pose.js';

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
    this.clips = createBuiltinClips(mesh);
    this.helper = new MMDAnimationHelper({ sync: false, resetPhysicsOnLoop: false });
    this.helper.onBeforePhysics = model => { this.behavior?.applyBones(); model.updateMatrixWorld(true); };
    this.helper.add(mesh, { animation: this.clips.idle, physics: true,
      unitStep: 1 / 65, maxStepNum: 3, warmup: 30 });
    const objects = this.helper.objects.get(mesh);
    this.mixer = objects.mixer;
    this.baseAction = this.mixer.clipAction(this.clips.idle);
    this.vmdCache = new Map();
    this.maskedIdleCache = new Map();
    this.motionGeneration = 0;
    this.physics = objects.physics;
    this.activeAction = null;
    this.finishedAction = null;
    this.motion = 'idle';
    this.poseProfile = null;
    this.poseCache = new Map();
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
    this.restoreIdle();
    if (this.activeAction) this.activeAction.stop();
    this.motionGeneration++;
    this.activeAction = null;
    this.finishedAction = null;
    this.motion = group;
    const leavingPose=!!this.poseProfile;
    this.poseProfile = null;
    this.helper.enable('ik',true);
    this.helper.enable('physics',this.physicsEnabled);
    this.behavior.setMotionClip(null);
    this.behavior.setManualMotion(group!=='idle');
    if (group !== 'idle') {
      this.activeAction = this.mixer.clipAction(this.clips[group]);
      this.activeAction.reset().setLoop(THREE.LoopOnce, 1).play();
    }
    this.evaluatePose();
    if(leavingPose)this.physics.reset();
  }

  async loadSideLying(url) {
    const target=this.mesh,request=++this.motionGeneration;
    if(!this.poseCache.has(url))this.poseCache.set(url,loadLayingPose(url,target));
    let clip;
    try {clip=await this.poseCache.get(url);}catch(error){this.poseCache?.delete(url);if(this.mesh&&request===this.motionGeneration)throw error;return;}
    if(!this.mesh||request!==this.motionGeneration)return;
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

  restoreIdle() {
    if (this.baseAction.getClip() === this.clips.idle) return;
    const previous = this.baseAction;
    // 先激活新的待机绑定，再解除旧动作；共有骨骼不会暂时恢复 T pose。
    this.baseAction = this.mixer.clipAction(this.clips.idle).reset().play();
    previous.stop();
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
    this.helper.enable('physics', false);
    this.helper.update(0);
    this.physics.reset();
    this.helper.enable('physics', this.physicsEnabled);
  }

  setPhysics(enabled) {
    this.physicsEnabled = enabled;
    this.helper.enable('physics', enabled && !this.poseProfile);
    if (enabled) this.physics.reset();
  }

  resetPhysics() {
    const enabled = this.physicsEnabled;
    this.helper.enable('physics', false);
    this.behavior.prepareFrame();
    this.helper.update(0);
    this.physics.reset();
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
    this.helper.update(delta);
    if (this.finishedAction === this.activeAction && this.finishedAction) {
      this.restoreIdle();
      this.activeAction.stop();
      this.activeAction = this.finishedAction = null;
      this.motion = 'idle';
      this.behavior.setMotionClip(null);
      this.behavior.setManualMotion(false);
      this.evaluatePose();
    }
    else {
      if(!this.physicsEnabled||this.poseProfile)this.behavior.applyBones();
      this.behavior.applyFace();
    }
    this.mesh.updateMatrixWorld(true);
    this.frames++;
    this.elapsed += delta;
    if (this.physicsEnabled && !this.poseProfile) this.steps++;
  }

  snapshot() {
    let motionAngle = 0;
    this.dynamicBodies.forEach((b, i) => {
      motionAngle = Math.max(motionAngle, b.bone.quaternion.angleTo(this.restRotations[i]));
    });
    return { motion: this.motion, physics_enabled: this.physicsEnabled,
      physics_active:this.physicsEnabled&&!this.poseProfile,pose_profile:this.poseProfile,
      engine: 'Ammo/Bullet', rigid_bodies: this.physics.bodies.length,
      constraints: this.physics.constraints.length, dynamic_bones: this.dynamicBodies.length,
      frames: this.frames, physics_steps: this.steps, dynamic_bone_angle: motionAngle,
      motion_time: this.activeAction?.time || 0, animation_time: this.elapsed,
      document_hidden: document.hidden,
      head_rotation: this.mesh.skeleton.bones.find(b => b.name === '頭')?.rotation.toArray().slice(0, 3),
      torso_position: this.mesh.skeleton.bones.find(b => b.name === '上半身')?.position.toArray(),
      right_arm_rotation: this.mesh.skeleton.bones.find(b => b.name === '右腕')?.rotation.toArray().slice(0, 3),
      left_arm_rotation: this.mesh.skeleton.bones.find(b => b.name === '左腕')?.rotation.toArray().slice(0, 3),
      right_palm_normal: palmNormal(this.mesh)?.toArray(),
      wasm_heap_bytes: this.ammo.HEAP8.length, paused: this.paused,
      behavior:this.behavior.snapshot() };
  }

  dispose() {
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.mesh);
    this.helper.remove(this.mesh);
    this.mesh = this.helper = this.physics = this.mixer = this.ammo = null;
    this.dynamicBodies = this.restRotations = this.clips = this.activeAction = null;
    this.vmdCache.clear(); this.vmdCache = this.baseAction = null;
    this.poseCache.clear();this.poseCache=null;
    this.maskedIdleCache.clear(); this.maskedIdleCache = null;
    this.behavior = null;
    window.Ammo = null;
  }
}
