import * as THREE from 'three';
import { MMDLoader } from 'three/addons/loaders/MMDLoader.js';
import { configureMaterials } from './materials.js';
import { AnimationRuntime, createPhysicsModule } from './animation_runtime.js';
import { expressions, behaviorMorphNames } from './behavior.js';
import { gestureGeometry } from './calibrated_gestures.js';
import { classifyTouch, reactToTouch } from './interaction.js';
import {installGroundSupport,setGroundSupport,visibleBounds} from './ground_support.js';
import {transitionAssets} from './pose_transitions.js';
import {matchRig} from './rig/matcher.js';
import {createRigAccess} from './rig/access.js';
import {validateMorphMap,mappedMorphNames} from './rig/morphs.js';

let bridge, mesh, frameBounds, standingBounds, runtime, generation=0, stopped=false;
let viewMode='full', headTarget=null, headScale=1;
let upperBodyIndices=[];
let cameraEase=null, cameraInitialized=false, previousPosture=null;
const cameraCenter=new THREE.Vector3();
const viewAngles={head_front:0,head_left:-0.55,head_right:0.55};
const scene=new THREE.Scene();
const camera=new THREE.OrthographicCamera(-10,10,15,-15,0.1,200);
const renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,preserveDrawingBuffer:true});
renderer.setClearColor(0x000000,0);
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.outputColorSpace=THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,1.0));
const key=new THREE.DirectionalLight(0xffffff,0.85);
key.position.set(-8,25,30);
scene.add(key);
const fill=new THREE.DirectionalLight(0xffe7ed,0.25);
fill.position.set(8,15,10);
scene.add(fill);

function render(){renderer.render(scene,camera);}
function reportRuntime(){
  if(runtime && bridge)bridge.runtimeStatus(JSON.stringify(snapshot()));
}
// 过渡保留全身；躺稳后同一套近景菜单改用横躺上半身取景。
function effectiveViewMode(){return runtime?.poseProfile&&runtime.motion!=='side_lying'?'full':viewMode;}
function snapshot(){return runtime?{...runtime.snapshot(),view_mode:viewMode,
  effective_view_mode:effectiveViewMode(),interaction:interactionLayout(),
  camera_frame:{height:camera.top-camera.bottom,floor_y:runtime.transitions?
    (1-new THREE.Vector3(0,runtime.transitions.floor,0).project(camera).y)*innerHeight/2:null}}:null;}
let lastFrame=0,lastReport=0;
function animate(now,inputs={}){
  if(stopped)return;
  const delta=lastFrame?Math.max(0,(now-lastFrame)/1000):0;
  lastFrame=now;
  if(runtime && !runtime.paused){
    if(inputs.pointer)runtime.behavior.setPointer(inputs.pointer.x,inputs.pointer.y,inputs.pointer.manual||false);
    if(inputs.audio)runtime.behavior.setAudio(inputs.audio.value,inputs.audio.active);
    if(inputs.activity)runtime.behavior.setActivity(inputs.activity);
    runtime.update(delta);render();
    if(runtime.asyncMotionError){bridge.motionError(runtime.asyncMotionError);runtime.asyncMotionError=null;}
    if(runtime.poseProfile!==previousPosture){previousPosture=runtime.poseProfile;
      frameBounds=(runtime.poseProfile&&runtime.transitions?runtime.transitions.bounds:standingBounds).clone();resize(true);reportRuntime();}
    if(cameraEase){
      cameraEase.time+=Math.min(delta,.05);const t=Math.min(1,cameraEase.time/.65),w=t*t*t*(t*(t*6-15)+10);
      const height=THREE.MathUtils.lerp(cameraEase.height,cameraEase.targetHeight,w),aspect=innerWidth/innerHeight;
      camera.top=height/2;camera.bottom=-height/2;camera.left=-height*aspect/2;camera.right=height*aspect/2;
      camera.position.lerpVectors(cameraEase.position,cameraEase.targetPosition,w);
      const target=cameraEase.center.clone().lerp(cameraEase.targetCenter,w);cameraCenter.copy(target);camera.lookAt(target);camera.updateProjectionMatrix();
      if(t===1)cameraEase=null;render();
    }
  }
  if(now-lastReport>500){lastReport=now;reportRuntime();}
}
function resize(smooth=false){
  const w=Math.max(innerWidth,1),h=Math.max(innerHeight,1),aspect=w/h;
  renderer.setSize(w,h);
  if(frameBounds){
    const size=frameBounds.getSize(new THREE.Vector3());
    const center=frameBounds.getCenter(new THREE.Vector3());
    let viewHeight=Math.max(size.y*1.10,size.x/aspect*1.10);
    if(runtime?.transitions){
      const bounds=runtime.transitions.bounds,floor=runtime.transitions.floor;
      viewHeight=Math.max((standingBounds.max.y-floor)/.9,(bounds.max.y-floor)/.9);
      if(runtime.poseProfile)viewHeight=Math.max(viewHeight,Math.max(Math.abs(bounds.min.x),Math.abs(bounds.max.x))*2/aspect/.9);
      else viewHeight=Math.max(viewHeight,size.x/aspect*1.1);
      center.set(0,floor+viewHeight*.45,0);
    }
    const closeUp=effectiveViewMode()!=='full'&&headTarget;
    if(closeUp){
      if(runtime?.motion==='side_lying'){
        const frame=sideCloseUpFrame(viewAngles[viewMode],aspect);
        center.copy(frame.center);viewHeight=frame.height;
      }else{
        center.copy(headTarget);
        // 正常宽画布保留近景大小，窄屏仍给胸前手势留出余量。
        viewHeight=Math.max(11.5,17.5/aspect)*headScale;
      }
    }
    const oldHeight=camera.top-camera.bottom,oldPosition=camera.position.clone();
    const oldCenter=cameraCenter.clone();
    camera.left=-viewHeight*aspect/2;camera.right=viewHeight*aspect/2;
    camera.top=viewHeight/2;camera.bottom=-viewHeight/2;
    if(closeUp){
      const angle=viewAngles[viewMode];
      camera.position.copy(center).add(new THREE.Vector3(Math.sin(angle)*45,0,Math.cos(angle)*45));
      camera.lookAt(center);
    }else{camera.position.set(center.x,center.y,55);camera.lookAt(center.x,center.y,0);}
    camera.updateProjectionMatrix();
    cameraCenter.copy(center);
    if(smooth&&cameraInitialized){
      cameraEase={time:0,height:oldHeight,position:oldPosition,center:oldCenter,targetHeight:viewHeight,targetPosition:camera.position.clone(),targetCenter:center.clone()};
      camera.position.copy(oldPosition);camera.top=oldHeight/2;camera.bottom=-oldHeight/2;camera.left=-oldHeight*aspect/2;camera.right=oldHeight*aspect/2;
      camera.lookAt(oldCenter);camera.updateProjectionMatrix();
      cameraCenter.copy(oldCenter);
    }else cameraEase=null;
    cameraInitialized=true;
  }
  render();
}
function setViewMode(mode){
  if(mode!=='full'&&!Object.hasOwn(viewAngles,mode))return false;
  viewMode=mode;resize(runtime?.motion==='side_lying');reportRuntime();return true;
}
addEventListener('resize',()=>resize(!!cameraEase));
function fitCurrentPose(){
  if(!mesh)return;
  mesh.updateMatrixWorld(true);mesh.skeleton.update();mesh.computeBoundingBox();
  frameBounds=mesh.boundingBox.clone();resize();
}
function upperBodyPoints(){
  if(!mesh)return [];
  mesh.updateMatrixWorld(true);mesh.skeleton.update();
  const support=mesh.userData.groundSupport,point=new THREE.Vector3();
  return upperBodyIndices.map(i=>{
    mesh.getVertexPosition(i,point);
    if(support?.enabled.value)point.y=Math.max(point.y,support.floor.value+.035);
    return point.clone().applyMatrix4(mesh.matrixWorld);
  });
}
function sideCloseUpFrame(angle,aspect){
  // 用当前蒙皮轮廓，不能沿用站立时缓存的胸口位置；排除腿、裙尾与尾巴。
  const inverse=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),-angle);
  const box=new THREE.Box3();
  for(const point of upperBodyPoints())box.expandByPoint(point.applyQuaternion(inverse));
  const center=box.getCenter(new THREE.Vector3()).applyQuaternion(inverse.invert());
  const size=box.getSize(new THREE.Vector3());
  return {center,height:Math.max(8.5*headScale,size.y*1.18,size.x/aspect*1.18)};
}
function upperBodyFraming(){
  const points=upperBodyPoints().map(p=>p.project(camera));
  return {fully_visible:points.length>0&&points.every(p=>[p.x,p.y,p.z].every(Number.isFinite)&&Math.abs(p.x)<=1&&Math.abs(p.y)<=1&&Math.abs(p.z)<=1),
    left:Math.min(...points.map(p=>(p.x+1)/2)),right:Math.max(...points.map(p=>(p.x+1)/2)),
    top:Math.min(...points.map(p=>(1-p.y)/2)),bottom:Math.max(...points.map(p=>(1-p.y)/2))};
}
function framing(){
  if(!mesh)return null;
  const box=visibleBounds(mesh),points=[];
  for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z])
    points.push(new THREE.Vector3(x,y,z).applyMatrix4(mesh.matrixWorld).project(camera));
  return {fully_visible:points.every(p=>[p.x,p.y,p.z].every(Number.isFinite)&&Math.abs(p.x)<=1&&Math.abs(p.y)<=1&&Math.abs(p.z)<=1),
    left:Math.min(...points.map(p=>(p.x+1)/2)),right:Math.max(...points.map(p=>(p.x+1)/2)),
    top:Math.min(...points.map(p=>(1-p.y)/2)),bottom:Math.max(...points.map(p=>(1-p.y)/2)),width:innerWidth,height:innerHeight};
}
function dispose(model){
  if(!model)return;
  if(runtime?.mesh===model){runtime.dispose();runtime=null;}
  scene.remove(model);
  const textures=new Set();
  for(const mat of model.material){
    for(const value of Object.values(mat))if(value?.isTexture)textures.add(value);
    for(const uniform of Object.values(mat.uniforms||{}))if(uniform.value?.isTexture)textures.add(uniform.value);
    mat.dispose();
  }
  for(const texture of textures)texture.dispose();
  model.geometry.dispose();model.skeleton.dispose();
}

async function loadModel(url,requestId,textureOverrides={},options={}){
  const current=++generation;
  dispose(mesh);mesh=null;frameBounds=null;render();
  cameraEase=null;cameraInitialized=false;previousPosture=null;
  let candidate;
  try{
    const loader=new MMDLoader();
    const data=await new Promise((resolve,reject)=>loader.loadPMX(url,resolve,undefined,reject));
    if(current!==generation)return;
    const originalMorphCount=data.morphs.length;
    // 只保留已实现的顶点表情，避免为百余个表情分配数百 MB 的显存。
    if(options.morph_map)validateMorphMap(options.morph_map,data.morphs.filter(m=>m.type===1).map(m=>m.name));
    const names=new Set(options.morph_map?mappedMorphNames(options.morph_map):behaviorMorphNames);
    data.morphs=data.morphs.filter(m=>m.type===1 && names.has(m.name));
    data.metadata.morphCount=data.morphs.length;
    const manager=new THREE.LoadingManager();
    manager.setURLModifier(u=>{
      const normalized=u.replaceAll('\\','/');
      return textureOverrides[normalized]||normalized;
    });
    const materialsReady=new Promise((resolve,reject)=>{
      manager.onLoad=resolve;
      manager.onError=u=>reject(new Error('贴图无法读取：'+u));
    });
    const builder=new MMDLoader(manager).meshBuilder;
    candidate=builder.build(data,url.slice(0,url.lastIndexOf('/')+1));
    await materialsReady;
    if(current!==generation){dispose(candidate);return;}
    const materialInfo=configureMaterials(candidate.material);
    const rigReport=options.rig_map||matchRig(data,{name:data.metadata.modelName,
      sha256:options.model_hash,boneCount:data.bones.length});
    options.rig=createRigAccess(candidate,rigReport,options.model_hash);
    installGroundSupport(candidate);
    const ammo=await createPhysicsModule();
    if(current!==generation){dispose(candidate);return;}
    if(options.transition_url){
      try{
        const response=await fetch(options.transition_url);if(!response.ok)throw new Error('动作文件无法读取');
        options.transitions=transitionAssets(await response.json(),options.model_hash,candidate);
      }catch(error){options.transition_error=String(error.message||error);console.warn(options.transition_error);}
      if(current!==generation){dispose(candidate);return;}
    }
    runtime=new AnimationRuntime(candidate,ammo,options);
    candidate.updateMatrixWorld(true);
    candidate.skeleton.update();
    candidate.computeBoundingBox();
    frameBounds=candidate.boundingBox.clone();
    standingBounds=frameBounds.clone();
    mesh=candidate;
    const chest=runtime.rig.upperTorso()?.getWorldPosition(new THREE.Vector3())||frameBounds.getCenter(new THREE.Vector3());
    const neck=(runtime.rig.get('neck')||runtime.rig.get('head'))?.getWorldPosition(new THREE.Vector3())||chest.clone().add(new THREE.Vector3(0,2.593,0));
    headScale=Math.max(.1,chest.distanceTo(neck)/2.593);
    headTarget=chest.clone().add(new THREE.Vector3(0,2.7,2).multiplyScalar(headScale));
    const waistBone=runtime.rig.get('spine_mid')||runtime.rig.get('spine');
    const waist=(waistBone?waistBone.getWorldPosition(new THREE.Vector3()).y:chest.y)-.8*headScale;
    const positions=mesh.geometry.attributes.position,skinIndex=mesh.geometry.attributes.skinIndex,skinWeight=mesh.geometry.attributes.skinWeight;
    upperBodyIndices=[];
    for(let i=0;i<positions.count;i++){
      let lowerCloth=false,hand=false;
      for(let j=0;j<4;j++)if(skinWeight.getComponent(i,j)>.15){
        const name=mesh.skeleton.bones[skinIndex.getComponent(i,j)]?.name||'';
        lowerCloth ||= /^Tail_|Dress|ZSpring_(Thigh|Calf|Leg)/.test(name);
        hand ||= /^[左右](手首|[親人中薬小]指)/.test(name);
      }
      if(!lowerCloth&&(positions.getY(i)>=waist||hand))upperBodyIndices.push(i);
    }
    if(options.view_mode==='full'||Object.hasOwn(viewAngles,options.view_mode))viewMode=options.view_mode;
    scene.add(mesh);resize();
    const expressionMap=runtime.behavior.expressions;
    const supported=Object.keys(expressionMap).filter(name=>name==='normal'||
      Object.keys(expressionMap[name]).every(m=>m in mesh.morphTargetDictionary));
    const info={vertices:data.metadata.vertexCount,triangles:data.metadata.faceCount,
      bones:data.metadata.boneCount,materials:data.metadata.materialCount,morphs:originalMorphCount,
      active_morphs:data.morphs.length,expressions:supported,texture_errors:0,
      texture_overrides:Object.keys(textureOverrides).length,
      material_alpha:materialInfo,motions:Object.keys(runtime.clips),character:options.character||null,runtime:snapshot()};
    render();bridge.modelResult(requestId,true,JSON.stringify(info));
  }catch(error){
    dispose(candidate);
    if(current===generation){console.error(error);bridge.modelResult(requestId,false,String(error.message||error));}
  }
}
function setExpression(name){
  if(!mesh || !(name in runtime.behavior.expressions))return false;
  runtime.behavior.setExpression(name);
  runtime.update(0);
  render();return true;
}
function interactionLayout(){
  const head=runtime?.rig?.get('head');
  if(!head)return {face:{x:0.5,y:0.22}};
  const position=head.getWorldPosition(new THREE.Vector3());position.y+=0.4;position.project(camera);
  // 头顶徽标留出狐耳高度，随头部转动与相机缩放一起投影。
  const top=head.getWorldPosition(new THREE.Vector3());top.y+=3.4;top.project(camera);
  return {face:{x:(position.x+1)/2,y:(1-position.y)/2},head_top:{x:(top.x+1)/2,y:(1-top.y)/2}};
}
const raycaster=new THREE.Raycaster();
function pickTouch(x,y){
  if(!runtime||!mesh)return null;
  mesh.updateMatrixWorld(true);mesh.skeleton.update();
  raycaster.setFromCamera(new THREE.Vector2(x*2-1,1-y*2),camera);
  const hit=raycaster.intersectObject(mesh,false)[0];
  if(!hit)return null;
  let part=classifyTouch(mesh,hit);
  const head=runtime.rig.get('head')?.getWorldPosition(new THREE.Vector3());
  if(runtime.poseProfile&&head&&head.distanceTo(hit.point)<2.2)part='head';
  return {part,side:Math.sign(hit.point.x-(head?.x||0))||1};
}
function touchAt(x,y){
  const hit=pickTouch(x,y);
  if(!hit||!reactToTouch(runtime,hit.part,hit.side))return null;
  reportRuntime();return hit.part;
}
function playMotion(name,url=null){
  if(!runtime)return false;
  if(name==='side_lying'&&url){
    const active=runtime;
    active.loadSideLying(url).then(()=>{if(active===runtime&&active.poseProfile){
      if(active.transitions){frameBounds=active.transitions.bounds.clone();previousPosture=active.poseProfile;resize(true);}
      else fitCurrentPose();reportRuntime();}})
      .catch(error=>{if(active===runtime)bridge.motionError(String(error.message||error));});
  }else if(url){
    const active=runtime;
    active.loadVmd(url,name).then(()=>{if(active===runtime&&!active.poseProfile){frameBounds=standingBounds.clone();resize();reportRuntime();}})
      .catch(error=>{console.error(error);if(active===runtime)bridge.motionError(String(error.message||error));});
  }else{runtime.play(name);if(!runtime.poseProfile){frameBounds=standingBounds.clone();resize();}reportRuntime();}
  return true;
}
window.HsinPmx={loadModel,setExpression,playMotion,setViewMode,
  touchAt,
  setParameters:params=>runtime?.behavior.setParameters(params),
  setLookAt:(x,y)=>runtime?.behavior.setPointer(x,y,true),
  setBehavior:settings=>{
    if(settings.reset_parameters)runtime?.behavior.clearParameters();
    const {reset_parameters,...flags}=settings;runtime?.behavior.setSettings(flags);reportRuntime();
  },
  blink:()=>runtime?.behavior.forceBlink(),
  setLipSync:(value,shape,duration)=>runtime?.behavior.setLip(value,shape,duration),
  setActivity:activity=>{runtime?.behavior.setActivity(activity);reportRuntime();},
  setMood:mood=>{runtime?.behavior.setMood(mood);reportRuntime();},
  tick:animate,
  setPhysics:enabled=>{if(runtime){runtime.setPhysics(enabled);reportRuntime();}},
  resetPhysics:()=>{if(runtime){runtime.resetPhysics();reportRuntime();}},
  setPaused:paused=>{if(runtime){runtime.paused=paused;runtime.behavior.suspend();lastFrame=0;reportRuntime();}},
  snapshot,
  framing,
  upperBodyFraming,
  dispose:()=>{stopped=true;generation++;dispose(mesh);mesh=null;renderer.dispose();}};
// 开发检查只改镜头、不改姿态；正常窗口不会调用。重置后仍沿用产品原有取景。
window.HsinPmxDebug={
  // 实际求值后的语义骨坐标，用于新角色骨轴/姿态检查，不写回 PMX。
  rigGeometry:()=>{
    if(!runtime?.rig)return null;
    mesh.updateMatrixWorld(true);mesh.skeleton.update();mesh.computeBoundingBox();
    return {points:Object.fromEntries(Object.entries(runtime.rig.report.bones)
      .filter(([id])=>runtime.rig.get(id)).map(([id])=>[id,runtime.rig.get(id).getWorldPosition(new THREE.Vector3()).toArray()])),
      finite:mesh.skeleton.bones.every(b=>[...b.position,...b.quaternion,...b.scale].every(Number.isFinite)),
      bounds:{min:mesh.boundingBox.min.toArray(),max:mesh.boundingBox.max.toArray()}};
  },
  previewTransition:async(url,name,time)=>{
    const data=await fetch(url).then(r=>r.json());
    runtime.behavior.prepareFrame();runtime.helper.enable('physics',false);runtime.paused=true;
    mesh.skeleton.bones.forEach((b,i)=>{b.position.copy(runtime.bindPose[i].position);b.quaternion.copy(runtime.bindPose[i].rotation);});
    const bones=new Map(mesh.skeleton.bones.map(b=>[b.name,b]));
    for(const track of [...data.freeze,...data.clips[name].tracks]){
      const bone=bones.get(track.name.match(/\.bones\[(.*?)\]/)[1]);
      const key=track.type==='quaternion'?new THREE.QuaternionKeyframeTrack(track.name,track.times,track.values):new THREE.VectorKeyframeTrack(track.name,track.times,track.values);
      const value=key.createInterpolant().evaluate(time);
      if(track.type==='quaternion')bone.quaternion.fromArray(value);else bone.position.fromArray(value);
    }
    runtime.helper.objects.get(mesh).grantSolver.update();
    mesh.updateMatrixWorld(true);mesh.skeleton.update();mesh.computeBoundingBox();
    setGroundSupport(mesh,data.floor,true);
    frameBounds=new THREE.Box3(new THREE.Vector3(-16,-1,-15),new THREE.Vector3(16,25,15));resize();
    return {bounds:{min:mesh.boundingBox.min.toArray(),max:mesh.boundingBox.max.toArray()},geometry:gestureGeometry(mesh)};
  },
  geometry:()=>mesh?gestureGeometry(mesh):null,
  visibleBandFraming:()=>{
    if(!mesh)return null;
    // 全身包围盒的空角和画面下方的裙摆不能代表近景手臂是否裁切。
    mesh.updateMatrixWorld(true);mesh.skeleton.update();
    let left=Infinity,right=-Infinity;
    const p=new THREE.Vector3();
    for(let i=0;i<mesh.geometry.attributes.position.count;i++){
      mesh.getVertexPosition(i,p).applyMatrix4(mesh.matrixWorld).project(camera);
      if(p.y>=-1&&p.y<=1){left=Math.min(left,(p.x+1)/2);right=Math.max(right,(p.x+1)/2);}
    }
    return {left,right,width:innerWidth,height:innerHeight};
  },
  pickTouch:(x,y)=>pickTouch(x,y)?.part||null,
  projectPoint:coords=>{
    const p=new THREE.Vector3(...coords).project(camera);return {x:(p.x+1)/2,y:(1-p.y)/2};
  },
  view:(angle=0)=>{
    if(!mesh)return;
    const chest=mesh.skeleton.bones.find(b=>b.name==='上半身2').getWorldPosition(new THREE.Vector3());
    const target=chest.clone().add(new THREE.Vector3(0,1.7,2));
    const h=7.5,aspect=Math.max(innerWidth,1)/Math.max(innerHeight,1);
    camera.left=-h*aspect/2;camera.right=h*aspect/2;camera.top=h/2;camera.bottom=-h/2;
    camera.position.copy(target).add(new THREE.Vector3(Math.sin(angle)*45,0,Math.cos(angle)*45));
    camera.lookAt(target);camera.updateProjectionMatrix();render();
  },
  resetView:()=>resize(),
};
new QWebChannel(qt.webChannelTransport,channel=>{bridge=channel.objects.pmxBridge;bridge.viewerReady();});
resize();
