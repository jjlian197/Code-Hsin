import assert from 'node:assert/strict';
import * as THREE from 'three';
import {MMDAnimationHelper} from 'three/addons/animation/MMDAnimationHelper.js';

function fixture(afterPhysics=true){
  const bones=['main','before','after','dependent'].map(name=>Object.assign(new THREE.Bone(),{name}));
  bones[0].add(...bones.slice(1));
  const mesh=new THREE.SkinnedMesh(new THREE.BufferGeometry(),new THREE.MeshBasicMaterial());
  mesh.add(bones[0]);mesh.bind(new THREE.Skeleton(bones));
  const grants=[1,2,3].map(index=>({index,parentIndex:index===3?2:0,ratio:.5,isLocal:false,affectRotation:true,affectPosition:false}));
  mesh.geometry.userData.MMD={format:'pmx',bones:bones.map((b,index)=>({index,name:b.name,transformationClass:index===3?1:2,afterPhysics:afterPhysics&&index>=2,grant:grants.find(g=>g.index===index)})),grants,iks:[],rigidBodies:[],constraints:[]};
  const clip=new THREE.AnimationClip('fixed',1,[new THREE.QuaternionKeyframeTrack('.bones[main].quaternion',[0,1],[0,0,0,1,0,0,0,1])]);
  const helper=new MMDAnimationHelper({sync:false});helper.add(mesh,{animation:clip,physics:false});
  let calls=0;
  helper.objects.get(mesh).physics={update(){calls++;bones[0].quaternion.setFromAxisAngle(new THREE.Vector3(1,0,0),.6);},reset(){}};
  return {mesh,bones,helper,calls:()=>calls};
}
const angle=b=>new THREE.Euler().setFromQuaternion(b.quaternion).x;
const near=(actual,expected)=>assert(Math.abs(actual-expected)<1e-6,`${actual} != ${expected}`);
const staged=fixture();
for(let i=0;i<3;i++){
  staged.helper.update(1/30);
  near(angle(staged.bones[1]),0); // 物理前 Grant 读动画姿态。
  near(angle(staged.bones[2]),.3); // 物理后 Grant 读本帧 .6 弧度。
  near(angle(staged.bones[3]),.15); // 同阶段依赖先求父，且不重复叠加。
}
assert.equal(staged.calls(),3);
staged.helper.enable('physics',false);staged.helper.update(1/30);
near(angle(staged.bones[2]),0);near(angle(staged.bones[3]),0);
staged.helper.enable('grant',false);staged.helper.enable('physics',true);staged.helper.update(1/30);
near(angle(staged.bones[2]),0);
staged.helper.enable('grant',true);staged.helper.enable('physics',false);
staged.helper.onAfterPhysics=()=>staged.bones[0].quaternion.setFromAxisAngle(new THREE.Vector3(1,0,0),.8);
staged.helper.update(1/30);near(angle(staged.bones[2]),.4); // 静息冻结姿态在第二阶段之前恢复。
const legacy=fixture(false);legacy.helper.update(1/30);near(angle(legacy.bones[2]),0);
const ik=fixture(),ikCalls=[];
for(const index of [1,3])ik.mesh.geometry.userData.MMD.bones[index].ik={target:index,links:[]};
ik.helper.objects.get(ik.mesh).ikSolver={updateOne(data){ikCalls.push([data.target,ik.calls()]);}};
ik.helper.update(1/30);assert.deepEqual(ikCalls,[[1,0],[3,1]],'IK 应分别位于物理前与回写后');
console.log('PASS physical writeback, Grant/IK ordering, repeated frames, toggles, frozen pose and unmarked legacy path');
