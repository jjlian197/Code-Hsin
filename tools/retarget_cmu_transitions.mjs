import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {Parser} from '../src/assets/pmx_viewer/lib/three/addons/libs/mmdparser.module.js';
import {FBXLoader} from '../src/assets/pmx_viewer/lib/three/addons/loaders/FBXLoader.js';
import {retargetLayingPose} from '../src/assets/pmx_viewer/laying_pose.js';
import {createBuiltinClips, palmNormal} from '../src/assets/pmx_viewer/motions.js';
import {MMDAnimationHelper} from '../src/assets/pmx_viewer/lib/three/addons/animation/MMDAnimationHelper.js';
import {groundedMaterial} from '../src/assets/pmx_viewer/ground_support.js';

const config=JSON.parse(execFileSync('python',['-X','utf8','-c',
  'import json; from src.core.app_config import load_config,project_path; c=load_config(); print(json.dumps({"pose":str(project_path(c["sprite"]["animation"]["side_lying"])),"models":{n:str(project_path(p)) for n,p in c["sprite"]["model"]["forms"].items()}}))'],{encoding:'utf8'}));
const buffer=path=>{const b=fs.readFileSync(path);return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);};
const asset=new FBXLoader().parse(buffer(config.pose),'');
const v=()=>new THREE.Vector3(),q=()=>new THREE.Quaternion();
const smooth=t=>{t=THREE.MathUtils.clamp(t,0,1);return t*t*t*(t*(t*6-15)+10);};
const tracked=['センター','下半身','上半身','上半身1','上半身2','首','頭',
  ...['右','左'].flatMap(s=>['肩','腕','ひじ','手首','足','ひざ','足首'].map(n=>s+n))];
const sources=Object.fromEntries(['113_08','140_03'].map(n=>[n,JSON.parse(fs.readFileSync(`.runtime/cmu/${n}.json`,'utf8'))]));

for(const [form,path] of Object.entries(config.models)){
  const data=new Parser().parsePmx(buffer(path),true),geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(data.vertices.flatMap(v=>v.position),3));
  geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute(data.vertices.flatMap(v=>[...v.skinIndices,0,0,0,0].slice(0,4)),4));
  geometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute(data.vertices.flatMap(v=>[...v.skinWeights,0,0,0,0].slice(0,4)),4));
  geometry.userData.MMD={rigidBodies:data.rigidBodies};
  const mesh=new THREE.SkinnedMesh(geometry),bones=data.bones.map(b=>{
    const bone=new THREE.Bone();bone.name=b.name;bone.position.fromArray(b.position);
    if(b.parentIndex>=0)bone.position.sub(new THREE.Vector3().fromArray(data.bones[b.parentIndex].position));return bone;
  });
  bones.forEach((b,i)=>(data.bones[i].parentIndex>=0?bones[data.bones[i].parentIndex]:mesh).add(b));
  mesh.bind(new THREE.Skeleton(bones));mesh.updateMatrixWorld(true);
  const map=new Map(bones.map(b=>[b.name,b]));
  const grants=data.bones.flatMap((b,i)=>b.grant?[{index:i,...b.grant,transformationClass:b.transformationClass}]:[])
    .sort((a,b)=>a.transformationClass-b.transformationClass||a.index-b.index);
  geometry.userData.MMD.grants=grants;
  const grantSolver=new MMDAnimationHelper().createGrantSolver(mesh);
  const update=()=>{for(const g of grants)bones[g.index].quaternion.identity();grantSolver.update();mesh.updateMatrixWorld(true);mesh.skeleton.update();};
  const p=n=>map.get(n).getWorldPosition(v());
  const rest=bones.map(b=>({p:b.position.clone(),q:b.quaternion.clone()}));
  const restore=()=>{bones.forEach((b,i)=>{b.position.copy(rest[i].p);b.quaternion.copy(rest[i].q);});update();};
  const capture=()=>Object.fromEntries(tracked.map(n=>[n,{q:map.get(n).quaternion.toArray(),p:map.get(n).position.toArray()}]));
  const apply=pose=>{for(const [n,value] of Object.entries(pose)){map.get(n).quaternion.fromArray(value.q);map.get(n).position.fromArray(value.p);}update();};
  const worldRotation=(n,r)=>{const b=map.get(n);b.quaternion.copy(b.parent.getWorldQuaternion(q()).invert().multiply(r)).normalize();update();};
  const aim=(n,child,dir)=>worldRotation(n,q().setFromUnitVectors(p(child).sub(p(n)).normalize(),dir.clone().normalize()).multiply(map.get(n).getWorldQuaternion(q())));
  const solveChain=(start,middle,end,target)=>{
    const a=p(start),b=p(middle),c=p(end),l1=a.distanceTo(b),l2=b.distanceTo(c);
    const axis=target.clone().sub(a),distance=THREE.MathUtils.clamp(axis.length(),Math.abs(l1-l2)+.001,l1+l2-.001);axis.normalize();
    const along=(l1*l1-l2*l2+distance*distance)/(2*distance),height=Math.sqrt(Math.max(0,l1*l1-along*along));
    const plane=b.clone().sub(a).addScaledVector(axis,-b.clone().sub(a).dot(axis));
    if(plane.lengthSq()<1e-6)plane.set(0,0,1).addScaledVector(axis,-axis.z);plane.normalize();
    const knee=a.clone().addScaledVector(axis,along).addScaledVector(plane,height);
    aim(start,middle,knee.sub(a));aim(middle,end,target.clone().sub(p(middle)));
  };
  const idle=createBuiltinClips(mesh).idle,mixer=new THREE.AnimationMixer(mesh);
  const idleAction=mixer.clipAction(idle).play();mixer.update(0);update();
  const standing=capture();mixer.stopAllAction();mixer.uncacheRoot(mesh);restore();apply(standing);
  const footAnchors=Object.fromEntries(['右','左'].map(s=>[s,p(s+'足首')]));
  mesh.computeBoundingBox();const floor=mesh.boundingBox.min.y;
  const hips=p('下半身'),hipOffset=hips.clone().sub(p('センター'));
  const sideClip=retargetLayingPose(asset,mesh);
  const sideMixer=new THREE.AnimationMixer(mesh);sideMixer.clipAction(sideClip).play();sideMixer.update(0);update();
  const lying=capture();sideMixer.stopAllAction();sideMixer.uncacheRoot(mesh);restore();apply(lying);
  // 撑头侧躺的腿沿裙摆叠放并略抬脚，释放原 FBX 斜向下的足部支撑。
  // 肘部成为末端支点，不能为了脚底把整个上半身垫高。
  for(const side of ['右','左']){
    for(const [joint,child] of [['足','ひざ'],['ひざ','足首']]){
      const direction=p(side+child).sub(p(side+joint)).normalize();direction.y=Math.max(direction.y,side==='右'?.10:.035);
      aim(side+joint,side+child,direction);
    }
    worldRotation(side+'足首',q().setFromAxisAngle(new THREE.Vector3(0,1,0),Math.PI/2));
  }
  map.get('センター').position.y+=floor+.25-p('右ひじ').y;update();Object.assign(lying,capture());
  mesh.computeBoundingBox();
  // 先把定格侧躺接到同一地面；身体轮廓用于支撑，服装随后独立适配。
  const dynamic=new Set(data.rigidBodies.filter(b=>b.type>0&&b.boneIndex>=0).map(b=>b.boneIndex));
  const skinVertices=new Set();let faceStart=0;
  for(const mat of data.materials){
    if(/Skin|^Hand|Glove|^Face_/.test(mat.name))
      for(const face of data.faces.slice(faceStart,faceStart+mat.faceCount))for(const i of face.indices)skinVertices.add(i);
    faceStart+=mat.faceCount;
  }
  const feet=new Set(data.bones.flatMap((b,i)=>/[左右](足首|つま先)/.test(b.name)?[i]:[]));
  const bodyVertices=data.vertices.flatMap((vertex,i)=>{
    const footWeight=vertex.skinWeights.reduce((sum,w,j)=>sum+(feet.has(vertex.skinIndices[j])?w:0),0);
    return (skinVertices.has(i)||footWeight>.8)&&vertex.skinWeights.every((w,j)=>w<.05||!dynamic.has(vertex.skinIndices[j]))?[i]:[];
  });
  const bodyMinimum=()=>{update();let min=Infinity;for(const i of bodyVertices)min=Math.min(min,mesh.getVertexPosition(i,v()).y);return min;};
  map.get('センター').position.y+=floor-bodyMinimum();update();Object.assign(lying,capture());
  const supportingHand=p('右手首');
  for(let i=0;i<3;i++){
    const elbow=p('右ひじ');elbow.y=floor+.28;
    aim('右腕','右ひじ',elbow.sub(p('右腕')));aim('右ひじ','右手首',supportingHand.clone().sub(p('右ひじ')));
    map.get('センター').position.y+=floor-bodyMinimum();update();
  }
  Object.assign(lying,capture());
  restore();apply(standing);
  const results={},envelope=new THREE.Box3();
  const vertexGround=new Set();faceStart=0;
  for(const mat of data.materials){
    if(groundedMaterial(mat.name))for(const face of data.faces.slice(faceStart,faceStart+mat.faceCount))for(const i of face.indices)vertexGround.add(i);
    faceStart+=mat.faceCount;
  }
  for(const [name,source,start,end,padIn,padOut] of [
    ['lie_down',sources['113_08'],0,600,.8,1.2],['get_up',sources['140_03'],150,870,.8,.9]]){
    const sourcePosition=(n,i)=>v().fromArray(source.positions[n][i]);
    const sourceRotation=(n,i)=>q().fromArray(source.rotations[n][i]);
    const flat=sourcePosition('head',name==='lie_down'?end:start).sub(sourcePosition('root',name==='lie_down'?end:start));flat.y=0;
    const yaw=Math.atan2(-1,0)-Math.atan2(flat.x,flat.z),align=q().setFromAxisAngle(new THREE.Vector3(0,1,0),yaw);
    const sourceStanding=name==='lie_down'?start:end;
    const sourceFloor=Math.min(...['lfoot','rfoot','ltoes','rtoes'].map(n=>sourcePosition(n,sourceStanding).y));
    const scale=(hips.y-floor)/(sourcePosition('root',sourceStanding).y-sourceFloor);
    const baseRoot=sourcePosition('root',name==='lie_down'?start:end).applyQuaternion(align);
    const duration=(end-start)/120+padIn+padOut,poses=[],times=[],contacts=[];let handAnchor;
    const initial=name==='lie_down'?standing:lying,final=name==='lie_down'?lying:standing;
    const mappedRoot=i=>{
      const rotation=align.clone().multiply(sourceRotation('root',i));
      const point=sourcePosition('root',i).applyQuaternion(align).sub(baseRoot).multiplyScalar(scale);
      point.y=(sourcePosition('root',i).y-sourceFloor)*scale+floor;
      return point.sub(hipOffset.clone().applyQuaternion(rotation));
    };
    const offsetStart=v().fromArray(initial['センター'].p).sub(mappedRoot(start));offsetStart.y=0;
    const offsetEnd=v().fromArray(final['センター'].p).sub(mappedRoot(end));offsetEnd.y=0;
    for(let sample=0;sample<=Math.round(duration*30);sample++){
      const time=Math.min(sample/30,duration),frame=Math.min(end,Math.max(start,Math.round(start+(time-padIn)*120)));
      restore();
      const sp=n=>sourcePosition(n,frame).applyQuaternion(align);
      const root=map.get('センター'),rotation=align.clone().multiply(sourceRotation('root',frame));
      root.quaternion.copy(rotation);
      const translated=sp('root').sub(baseRoot).multiplyScalar(scale);
      translated.y=(sourcePosition('root',frame).y-sourceFloor)*scale+floor;
      root.position.copy(translated.sub(hipOffset.clone().applyQuaternion(rotation)));update();
      // 在整个原动作段分配根位置修正，避免躺稳后最后一秒横移到目标姿势。
      root.position.add(offsetStart.clone().lerp(offsetEnd,smooth((frame-start)/(end-start))));update();
      for(const [from,to] of [['lowerback','上半身'],['upperback','上半身1'],['thorax','上半身2']])
        worldRotation(to,align.clone().multiply(sourceRotation(from,frame)));
      // ASF 颈骨有自身偏转；先减去站立参考的局部旋转，不能直接复制世界四元数。
      for(const [parent,from,to,limits] of [['thorax','lowerneck','首',[20,30,12]],['lowerneck','upperneck','頭',[35,45,18]]]){
        const reference=sourceRotation(parent,sourceStanding).invert().multiply(sourceRotation(from,sourceStanding));
        const local=sourceRotation(parent,frame).invert().multiply(sourceRotation(from,frame));
        const sourceAxes=align.clone().multiply(sourceRotation(parent,sourceStanding));
        const delta=sourceAxes.clone().multiply(local.multiply(reference.invert())).multiply(sourceAxes.invert());
        const angles=new THREE.Euler().setFromQuaternion(delta,'XYZ');
        ['x','y','z'].forEach((axis,i)=>angles[axis]=THREE.MathUtils.clamp(angles[axis],-limits[i]*Math.PI/180,limits[i]*Math.PI/180));
        map.get(to).quaternion.copy(q().fromArray(standing[to].q).multiply(q().setFromEuler(angles)));update();
      }
      for(const [s,l] of [['右','r'],['左','l']]){
        aim(s+'肩',s+'腕',sp(l+'clavicle').sub(sp('thorax')));
        aim(s+'腕',s+'ひじ',sp(l+'humerus').sub(sp(l+'clavicle')));
        aim(s+'ひじ',s+'手首',sp(l+'wrist').sub(sp(l+'humerus')));
        const wrist=map.get(s+'手首'),up=p(s+'中指２').sub(p(s+'手首')).normalize(),normal=palmNormal(mesh,s);
        const restFrame=q().setFromRotationMatrix(new THREE.Matrix4().makeBasis(v().crossVectors(up,normal).normalize(),up,normal));
        const desiredUp=sp(l+'fingers').sub(sp(l+'wrist')).normalize();
        const thumb=sp(l+'thumb').sub(sp(l+'wrist')).normalize();
        const desiredNormal=v().crossVectors(thumb,desiredUp).normalize().multiplyScalar(s==='右'?1:-1);
        const desiredFrame=q().setFromRotationMatrix(new THREE.Matrix4().makeBasis(v().crossVectors(desiredUp,desiredNormal).normalize(),desiredUp,desiredNormal));
        worldRotation(s+'手首',desiredFrame.multiply(restFrame.invert()).multiply(wrist.getWorldQuaternion(q())));
        const thigh=sp(l+'femur').sub(sp(l+'hipjoint')).normalize(),calf=sp(l+'tibia').sub(sp(l+'femur')).normalize();
        const bend=Math.acos(THREE.MathUtils.clamp(thigh.dot(calf),-1,1));
        if(bend>Math.PI*.81)calf.copy(thigh).applyQuaternion(q().setFromAxisAngle(v().crossVectors(thigh,sp(l+'tibia').sub(sp(l+'femur')).normalize()).normalize(),Math.PI*.81));
        aim(s+'足',s+'ひざ',thigh);aim(s+'ひざ',s+'足首',calf);
        aim(s+'足首',s+'つま先',sp(l+'foot').sub(sp(l+'tibia')));
      }
      const mapped=capture();
      if(time<padIn){
        const w=smooth(time/padIn);
        for(const n of tracked){mapped[n].q=q().fromArray(initial[n].q).slerp(q().fromArray(mapped[n].q),w).toArray();mapped[n].p=v().fromArray(initial[n].p).lerp(v().fromArray(mapped[n].p),w).toArray();}
      }else if(time>duration-padOut){
        const w=smooth((time-(duration-padOut))/padOut);
        for(const n of tracked){mapped[n].q=q().fromArray(mapped[n].q).slerp(q().fromArray(final[n].q),w).toArray();mapped[n].p=v().fromArray(mapped[n].p).lerp(v().fromArray(final[n].p),w).toArray();}
      }
      apply(mapped);
      map.get('センター').position.y+=floor-bodyMinimum();update();
      {
        const footWeight=name==='lie_down'?1-smooth((frame-156)/54):smooth((frame-720)/60);
        const handIn=name==='lie_down'?[180,240]:[390,450],handOut=name==='lie_down'?[360,420]:[600,660];
        const handWeight=time>=padIn&&time<=duration-padOut?smooth((frame-handIn[0])/(handIn[1]-handIn[0]))*(1-smooth((frame-handOut[0])/(handOut[1]-handOut[0]))):0;
        if(handWeight>0&&!handAnchor){handAnchor=p('右手首');handAnchor.y=floor+.25;}
        for(let iteration=0;iteration<2;iteration++){
          if(footWeight>0)for(const side of ['右','左']){
            const target=p(side+'足首').lerp(footAnchors[side],footWeight);
            solveChain(side+'足',side+'ひざ',side+'足首',target);
          }
          if(handWeight>0){
            const target=p('右手首').lerp(handAnchor,handWeight);
            const shoulder=p('右腕'),reach=shoulder.distanceTo(p('右ひじ'))+p('右ひじ').distanceTo(p('右手首'))-.02;
            const planar=target.clone().sub(shoulder);planar.y=0;
            const available=Math.sqrt(Math.max(0,reach*reach-(target.y-shoulder.y)**2));
            if(planar.length()>available){map.get('センター').position.add(planar.clone().normalize().multiplyScalar((planar.length()-available)*handWeight));update();}
            solveChain('右腕','右ひじ','右手首',target);
            const normal=palmNormal(mesh,'右'),delta=q().setFromUnitVectors(normal,new THREE.Vector3(0,-1,0));
            worldRotation('右手首',q().slerp(delta,handWeight).multiply(map.get('右手首').getWorldQuaternion(q())));
          }
          map.get('センター').position.y+=floor-bodyMinimum();update();
        }
        if(footWeight>.999||handWeight>.999)contacts.push({time,feet:footWeight>.999,hand:handWeight>.999,
          right_ankle:p('右足首').toArray(),left_ankle:p('左足首').toArray(),right_wrist:p('右手首').toArray()});
      }
      poses.push(capture());times.push(time);
    }
    // 真人快速屈膝与比例修正会放大角速度；对局部姿态做对称低通，首尾保持精确。
    const raw=poses.map(pose=>structuredClone(pose));
    for(let i=1;i<poses.length-1;i++){
      const pose={};
      for(const n of tracked){
        const rotation=q().fromArray(raw[i][n].q),point=v();let total=0;
        for(let j=-3;j<=3;j++){
          const index=Math.max(0,Math.min(raw.length-1,i+j)),weight=4-Math.abs(j);
          rotation.slerp(q().fromArray(raw[index][n].q),weight/(total+weight));
          point.addScaledVector(v().fromArray(raw[index][n].p),weight);total+=weight;
        }
        pose[n]={q:rotation.toArray(),p:point.divideScalar(total).toArray()};
      }
      poses[i]=pose;
    }
    for(let i=0;i<poses.length;i++){
      restore();apply(poses[i]);map.get('センター').position.y+=floor-bodyMinimum();update();poses[i]=capture();
      const frame=Math.min(end,Math.max(start,Math.round(start+(times[i]-padIn)*120)));
      const weight=name==='lie_down'?1-smooth((frame-156)/54):smooth((frame-720)/60);
      if(weight>0&&i>0&&i<poses.length-1){
        for(let iteration=0;iteration<3;iteration++){
          // 双脚接地时按目标腿长压低过高的源骨盆，不能把不可达的脚点当作已锁定。
          let lower=0;
          for(const side of ['右','左']){
            const hip=p(side+'足'),knee=p(side+'ひざ'),foot=p(side+'足首'),target=foot.clone().lerp(footAnchors[side],weight);
            const reach=hip.distanceTo(knee)+knee.distanceTo(foot)-.0001;
            const planar=hip.clone().sub(target);planar.y=0;
            const ceiling=target.y+Math.sqrt(Math.max(0,reach*reach-planar.lengthSq()));
            lower=Math.min(lower,(ceiling-hip.y)*weight);
          }
          map.get('センター').position.y+=lower;update();
          for(const side of ['右','左'])solveChain(side+'足',side+'ひざ',side+'足首',p(side+'足首').lerp(footAnchors[side],weight));
          map.get('センター').position.y+=floor-bodyMinimum();update();
        }
        poses[i]=capture();
      }
      const contact=contacts.find(c=>Math.abs(c.time-times[i])<.001);
      if(contact)Object.assign(contact,{right_ankle:p('右足首').toArray(),left_ankle:p('左足首').toArray(),right_wrist:p('右手首').toArray()});
      if(i%3===0||i===poses.length-1)for(let vertex=0;vertex<data.vertices.length;vertex++){
        const point=mesh.getVertexPosition(vertex,v());if(vertexGround.has(vertex))point.y=Math.max(point.y,floor+.035);envelope.expandByPoint(point);
      }
    }
    const tracks=tracked.flatMap(n=>[
      {name:`.bones[${n}].quaternion`,type:'quaternion',times,values:poses.flatMap(p=>p[n].q)},
      {name:`.bones[${n}].position`,type:'vector',times,values:poses.flatMap(p=>p[n].p)}]);
    results[name]={name,duration,tracks,source:source.source,range:[start,end],fps:30,contacts};
    console.log(form,name,'duration',duration,'scale',scale,'body vertices',bodyVertices.length);
  }
  const output={version:1,model_sha256:createHash('sha256').update(fs.readFileSync(path)).digest('hex'),floor,
    bounds:{min:envelope.min.toArray(),max:envelope.max.toArray()},standing,lying,clips:results,
    freeze:sideClip.tracks.filter(t=>!tracked.some(n=>t.name.includes(`[${n}]`))).map(t=>({name:t.name,type:t.ValueTypeName,times:[0],values:Array.from(t.values.slice(0,t.getValueSize()))}))};
  fs.mkdirSync('motions/hsin',{recursive:true});fs.writeFileSync(`motions/hsin/${form}.json`,JSON.stringify(output));
}
