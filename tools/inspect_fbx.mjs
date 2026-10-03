import fs from 'node:fs';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import { FBXLoader } from '../src/assets/pmx_viewer/lib/three/addons/loaders/FBXLoader.js';

const path=process.argv[2]||'Female Laying Pose (1).fbx';
const bytes=fs.readFileSync(path);
const root=new FBXLoader().parse(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'');
root.updateMatrixWorld(true);
const bones=[];root.traverse(node=>{if(node.isBone)bones.push({name:node.name,parent:node.parent.name,
  position:node.position.toArray(),quaternion:node.quaternion.toArray(),world:node.getWorldPosition(new THREE.Vector3()).toArray()});});
const clips=root.animations.map(clip=>({name:clip.name,duration:clip.duration,tracks:clip.tracks.map(t=>({name:t.name,count:t.times.length,
  time:[...t.times].slice(0,4),first:[...t.values].slice(0,t.getValueSize()),last:[...t.values].slice(-t.getValueSize())}))}));
const report={path,bones,clips};
const clip=root.animations.find(c=>c.tracks.length);
const mixer=new THREE.AnimationMixer(root);mixer.clipAction(clip).play();mixer.update(0);root.updateMatrixWorld(true);
report.posed=bones.filter((b,i)=>bones.findIndex(v=>v.name===b.name)===i).map(b=>({name:b.name,
  world:root.getObjectByName(b.name).getWorldPosition(new THREE.Vector3()).toArray()}));
fs.mkdirSync('.runtime',{recursive:true});fs.writeFileSync('.runtime/fbx-inspection.json',JSON.stringify(report,null,2));
console.log(JSON.stringify({path,boneCount:bones.length,clips:clips.map(c=>({name:c.name,duration:c.duration,tracks:c.tracks.length})),
  posed:report.posed.filter(b=>/Hips|Spine|Neck$|Head$|Shoulder$|Arm$|Hand$|UpLeg$|Leg$|Foot$/.test(b.name))},null,2));
