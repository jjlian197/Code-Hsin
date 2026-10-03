import * as THREE from 'three';
import { MMDLoader } from 'three/addons/loaders/MMDLoader.js';
import { configureMaterials } from './materials.js';
import { AnimationRuntime, createPhysicsModule } from './animation_runtime.js';
import { expressions, behaviorMorphNames } from './behavior.js';

let bridge, mesh, frameBounds, runtime, generation=0, stopped=false;
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
  if(runtime && bridge)bridge.runtimeStatus(JSON.stringify({...runtime.snapshot(),interaction:interactionLayout()}));
}
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
  }
  if(now-lastReport>500){lastReport=now;reportRuntime();}
}
function resize(){
  const w=Math.max(innerWidth,1),h=Math.max(innerHeight,1),aspect=w/h;
  renderer.setSize(w,h);
  if(frameBounds){
    const size=frameBounds.getSize(new THREE.Vector3());
    const center=frameBounds.getCenter(new THREE.Vector3());
    const viewHeight=Math.max(size.y*1.10,size.x/aspect*1.10);
    camera.left=-viewHeight*aspect/2;camera.right=viewHeight*aspect/2;
    camera.top=viewHeight/2;camera.bottom=-viewHeight/2;
    camera.position.set(center.x,center.y,55);
    camera.lookAt(center.x,center.y,0);
    camera.updateProjectionMatrix();
  }
  render();
}
addEventListener('resize',resize);
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
  let candidate;
  try{
    const loader=new MMDLoader();
    const data=await new Promise((resolve,reject)=>loader.loadPMX(url,resolve,undefined,reject));
    if(current!==generation)return;
    const originalMorphCount=data.morphs.length;
    // 只保留已实现的顶点表情，避免为百余个表情分配数百 MB 的显存。
    const names=new Set(behaviorMorphNames);
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
    const ammo=await createPhysicsModule();
    if(current!==generation){dispose(candidate);return;}
    runtime=new AnimationRuntime(candidate,ammo,options);
    candidate.updateMatrixWorld(true);
    candidate.skeleton.update();
    candidate.computeBoundingBox();
    frameBounds=candidate.boundingBox.clone();
    mesh=candidate;scene.add(mesh);resize();
    const supported=Object.keys(expressions).filter(name=>name==='normal'||
      Object.keys(expressions[name]).every(m=>m in mesh.morphTargetDictionary));
    const info={vertices:data.metadata.vertexCount,triangles:data.metadata.faceCount,
      bones:data.metadata.boneCount,materials:data.metadata.materialCount,morphs:originalMorphCount,
      active_morphs:data.morphs.length,expressions:supported,texture_errors:0,
      texture_overrides:Object.keys(textureOverrides).length,
      material_alpha:materialInfo,motions:Object.keys(runtime.clips),runtime:runtime.snapshot()};
    render();bridge.modelResult(requestId,true,JSON.stringify(info));
  }catch(error){
    dispose(candidate);
    if(current===generation){console.error(error);bridge.modelResult(requestId,false,String(error.message||error));}
  }
}
function setExpression(name){
  if(!mesh || !(name in expressions))return false;
  runtime.behavior.setExpression(name);
  runtime.update(0);
  render();return true;
}
function interactionLayout(){
  const head=mesh?.skeleton.bones.find(b=>b.name==='頭');
  if(!head)return {face:{x:0.5,y:0.22}};
  const position=head.getWorldPosition(new THREE.Vector3());position.y+=0.4;position.project(camera);
  return {face:{x:(position.x+1)/2,y:(1-position.y)/2}};
}
const raycaster=new THREE.Raycaster();
function touchAt(x,y){
  if(!runtime||!mesh)return null;
  mesh.updateMatrixWorld(true);mesh.skeleton.update();
  raycaster.setFromCamera(new THREE.Vector2(x*2-1,1-y*2),camera);
  const hit=raycaster.intersectObject(mesh,false)[0];
  if(!hit)return null;
  const world=name=>mesh.skeleton.bones.find(b=>b.name===name)?.getWorldPosition(new THREE.Vector3());
  const head=world('頭'),neck=world('首'),hands=[world('右手首'),world('左手首')].filter(Boolean);
  let part='body';
  if(head&&neck&&hit.point.y>neck.y&&Math.abs(hit.point.x-head.x)<1.6)part='head';
  else if(hands.some(p=>p.distanceTo(hit.point)<1.2))part='hand';
  else if(hit.face){
    const indices=mesh.geometry.attributes.skinIndex,weights=mesh.geometry.attributes.skinWeight;
    const names=[];
    for(const vertex of [hit.face.a,hit.face.b,hit.face.c])for(let j=0;j<4;j++){
      if(weights.getComponent(vertex,j)>0.25)names.push(mesh.skeleton.bones[indices.getComponent(vertex,j)]?.name||'');
    }
    // HairTail 是发辫，真正尾巴的蒙皮使用 Tail_*。
    if(names.some(n=>/^Tail_|尾|しっぽ/i.test(n)))part='tail';
  }
  if(runtime.behavior.touch(part)&&part==='hand'&&runtime.motion==='idle')runtime.play('wave');
  reportRuntime();return part;
}
function playMotion(name,url=null){
  if(!runtime)return false;
  if(url){
    const active=runtime;
    active.loadVmd(url,name).then(()=>{if(active===runtime)reportRuntime();})
      .catch(error=>{console.error(error);if(active===runtime)bridge.motionError(String(error.message||error));});
  }else{runtime.play(name);reportRuntime();}
  return true;
}
window.HsinPmx={loadModel,setExpression,playMotion,
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
  tick:animate,
  setPhysics:enabled=>{if(runtime){runtime.setPhysics(enabled);reportRuntime();}},
  resetPhysics:()=>{if(runtime){runtime.resetPhysics();reportRuntime();}},
  setPaused:paused=>{if(runtime){runtime.paused=paused;runtime.behavior.suspend();lastFrame=0;reportRuntime();}},
  snapshot:()=>runtime?.snapshot(),
  dispose:()=>{stopped=true;generation++;dispose(mesh);mesh=null;renderer.dispose();}};
new QWebChannel(qt.webChannelTransport,channel=>{bridge=channel.objects.pmxBridge;bridge.viewerReady();});
resize();
