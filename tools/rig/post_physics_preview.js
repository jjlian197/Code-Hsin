window.HsinPmxDebug.startRunningTrial = data => {
  const tracks=data.tracks.map(t=>t.type==='quaternion'?new THREE.QuaternionKeyframeTrack(t.name,t.times,t.values):new THREE.VectorKeyframeTrack(t.name,t.times,t.values));
  const clip=new THREE.AnimationClip('treadmill_trial',data.duration,tracks);
  if(!clip.validate())throw new Error('跑步轨道无效');
  runtime.mixer.stopAllAction();
  runtime.baseAction=runtime.mixer.clipAction(clip).reset().setLoop(THREE.LoopRepeat,Infinity).play();
  runtime.activeAction=null;runtime.finishedAction=null;runtime.motion='treadmill_trial';
  runtime.behavior.setManualMotion(true);runtime.behavior.setMotionClip(clip);
  runtime.helper.enable('ik',false); // FBX 是 FK，保留原腿 IK 会把跑步腿拉回站立。
  runtime.physicsIdleTime=0;runtime.physicsRestPose=null;
  runtime.helper.enable('physics',false);runtime.helper.update(0);runtime.physics.reset();runtime.helper.enable('physics',runtime.physicsEnabled);
  window.__trialStart=runtime.elapsed;
  return {duration:clip.duration,tracks:tracks.length};
};
window.HsinPmxDebug.runningState=()=>{
  mesh.updateMatrixWorld(true);
  const data=mesh.geometry.userData.MMD.bones,bones=mesh.skeleton.bones;
  const post=data.filter(b=>b.afterPhysics),details=post.filter(d=>d.name.startsWith('ZSpring_Spine_')&&d.grant?.affectRotation&&!d.grant.isLocal).map(d=>{
    const expected=new THREE.Quaternion().slerp(bones[d.grant.parentIndex].quaternion,d.grant.ratio);
    return {index:d.index,name:d.name,error:bones[d.index].quaternion.angleTo(expected),angle:bones[d.index].quaternion.angleTo(new THREE.Quaternion()),position:bones[d.index].getWorldPosition(new THREE.Vector3()).toArray()};
  });
  return {elapsed:runtime.elapsed-window.__trialStart,post_count:details.length,total_post:post.length,max_error:Math.max(0,...details.map(d=>d.error)),
    finite:bones.every(b=>[...b.position,...b.quaternion].every(Number.isFinite)),details,
    shoulder:bones.find(b=>b.name==='右腕').quaternion.toArray(),main:bones.find(b=>b.name==='右胸').quaternion.toArray(),
    physics_steps:runtime.steps,motion:runtime.motion};
};
