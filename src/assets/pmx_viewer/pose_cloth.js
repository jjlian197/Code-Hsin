import * as THREE from 'three';

const vector=()=>new THREE.Vector3(),quat=()=>new THREE.Quaternion();
const movable=name=>/Hair|Daimao|Dress|Sleeve|BreastTie|^Tail_/.test(name)&&!/Hairpin|Wanzi/.test(name);

// 侧躺专用骨骼布料：动画负责身体，粒子链负责衣发。与站立 Bullet 互斥。
// 使用骨长、PMX 相邻面片约束、身体胶囊和地面，避免原刚体在贴地姿态爆开。
export class PoseCloth {
  constructor(mesh, floor) {
    this.mesh=mesh;this.floor=floor;this.active=false;this.age=0;this.steps=0;
    const bones=mesh.skeleton.bones,metadata=mesh.geometry.userData.MMD;
    mesh.updateMatrixWorld(true);
    const bodies=metadata.rigidBodies.filter(b=>b.type>0&&b.boneIndex>=0&&movable(bones[b.boneIndex].name));
    const byBone=new Map();
    this.nodes=bodies.filter(b=>!byBone.has(b.boneIndex)&&byBone.set(b.boneIndex,true)).map(body=>({
      bone:bones[body.boneIndex],body,parent:null,children:[],target:vector(),lastTarget:vector(),
      point:vector(),previous:vector(),rotation:quat(),local:vector(),root:false,
      limit:/Hair|Daimao/.test(bones[body.boneIndex].name)?1.5:2.2,
    }));
    const lookup=new Map(this.nodes.map(n=>[n.bone,n]));
    for(const node of this.nodes){
      node.parent=lookup.get(node.bone.parent)||null;node.root=!node.parent;
      if(node.parent)node.parent.children.push(node);
    }
    const depth=n=>{let d=0;for(let p=n.bone.parent;p?.isBone;p=p.parent)d++;return d;};
    this.nodes.sort((a,b)=>depth(a)-depth(b));
    this.edges=this.nodes.filter(n=>n.parent).map(n=>({a:n.parent,b:n,length:0}));
    const bodyNodes=new Map(this.nodes.map(n=>[n.body,n]));
    for(const c of metadata.constraints||[]){
      const a=bodyNodes.get(metadata.rigidBodies[c.rigidBodyIndex1]),b=bodyNodes.get(metadata.rigidBodies[c.rigidBodyIndex2]);
      if(a&&b&&a!==b&&a.parent!==b&&b.parent!==a)this.edges.push({a,b,length:0,seam:true});
    }
    // 使用动画身体骨骼，不能拿动态衣发自身当碰撞体。
    const names=new Map(bones.map(b=>[b.name,b]));
    const pairs=[['下半身','上半身',.85],['上半身','上半身2',.72],['上半身2','首',.86],['首','頭',.55],
      ...['右','左'].flatMap(s=>[[s+'足',s+'ひざ',.85],[s+'ひざ',s+'足首',.65],[s+'腕',s+'ひじ',.42],[s+'ひじ',s+'手首',.35]])];
    this.capsules=pairs.filter(([a,b])=>names.has(a)&&names.has(b)).map(([a,b,r])=>({a:names.get(a),b:names.get(b),r,start:vector(),end:vector()}));
    this.temp=vector();this.segment=vector();this.nearest=vector();this.direction=vector();
    this.delta=quat();this.world=quat();this.inverse=new THREE.Matrix4();
  }

  targets() {
    this.mesh.updateMatrixWorld(true);
    for(const n of this.nodes){n.bone.getWorldPosition(n.target);n.bone.getWorldQuaternion(n.rotation);}
    for(const c of this.capsules){c.a.getWorldPosition(c.start);c.b.getWorldPosition(c.end);}
    for(const e of this.edges)e.length=e.a.target.distanceTo(e.b.target);
  }

  reset() {
    this.targets();
    for(const n of this.nodes){n.point.copy(n.target);n.previous.copy(n.target);n.lastTarget.copy(n.target);}
    this.age=0;this.active=true;
  }

  stop(){this.active=false;}

  project(n) {
    if(n.root){n.point.copy(n.target);return;}
    // 在动画基础上限制移动幅度；近身附件保持原有间隙，避免碰撞体把整件衣服撑大。
    this.temp.copy(n.point).sub(n.target);
    if(this.temp.lengthSq()>n.limit*n.limit)n.point.copy(n.target).add(this.temp.setLength(n.limit));
    for(const c of this.capsules){
      this.segment.copy(c.end).sub(c.start);
      const length=this.segment.lengthSq();
      const nearestTo=point=>this.nearest.copy(c.start).addScaledVector(this.segment,
        THREE.MathUtils.clamp(this.temp.copy(point).sub(c.start).dot(this.segment)/(length||1),0,1));
      const restDistance=n.target.distanceTo(nearestTo(n.target));
      const radius=Math.min(c.r+.06,Math.max(.06,restDistance-.025));
      nearestTo(n.point);this.direction.copy(n.point).sub(this.nearest);
      if(this.direction.lengthSq()<radius*radius){
        if(this.direction.lengthSq()<1e-10)this.direction.copy(n.target).sub(this.nearest);
        if(this.direction.lengthSq()<1e-10)this.direction.set(0,0,1);
        n.point.copy(this.nearest).add(this.direction.setLength(radius));
      }
    }
    n.point.y=Math.max(n.point.y,this.floor+.065);
  }

  update(delta, strength=1) {
    if(!this.active)this.reset();
    this.targets();this.age+=delta;
    // 跟随动画锚点的位移，再叠加阻尼惯性、重力与形状恢复；不把镜头变化作为外力。
    const dt=Math.min(delta,1/30),damping=Math.exp(-7*dt);
    for(const n of this.nodes){
      const shift=this.temp.copy(n.target).sub(n.lastTarget);
      n.point.addScaledVector(shift,.92);n.previous.addScaledVector(shift,.92);n.lastTarget.copy(n.target);
      if(n.root){n.point.copy(n.target);n.previous.copy(n.target);continue;}
      this.temp.copy(n.point).sub(n.previous).multiplyScalar(damping);
      n.previous.copy(n.point);n.point.add(this.temp);
      n.point.y-=26*dt*dt;
      n.point.lerp(n.target,1-Math.exp(-2.4*dt));
    }
    for(let iteration=0;iteration<6;iteration++){
      for(const e of this.edges){
        this.temp.copy(e.b.point).sub(e.a.point);const length=this.temp.length();
        if(length<1e-6)continue;
        const wa=e.a.root?0:1,wb=e.b.root?0:1;if(!wa&&!wb)continue;
        this.temp.multiplyScalar((length-e.length)/length/(wa+wb)*(e.seam?.65:1));
        e.a.point.addScaledVector(this.temp,wa);e.b.point.addScaledVector(this.temp,-wb);
      }
      for(const n of this.nodes)this.project(n);
    }
    const blend=THREE.MathUtils.smoothstep(this.age,0,.35)*strength;
    for(const n of this.nodes){
      this.world.copy(n.rotation);
      // 由链方向驱动弯曲，保留原有扭转；不让一个短节无限旋转。
      const child=n.children.reduce((best,c)=>!best||c.target.distanceToSquared(n.target)>best.target.distanceToSquared(n.target)?c:best,null);
      if(child){
        this.temp.copy(child.target).sub(n.target).normalize();this.direction.copy(child.point).sub(n.point).normalize();
        if(this.temp.lengthSq()>.1&&this.direction.lengthSq()>.1){
          this.delta.setFromUnitVectors(this.temp,this.direction);
          const angle=this.delta.angleTo(quat());if(angle>.6)this.delta.slerp(quat(),1-.6/angle);
          this.world.premultiply(this.delta);
        }
      }
      this.world.slerp(n.rotation,1-blend);
      n.local.copy(n.target).lerp(n.point,blend);
      n.bone.parent.updateWorldMatrix(true,false);
      n.bone.position.copy(n.local.applyMatrix4(this.inverse.copy(n.bone.parent.matrixWorld).invert()));
      n.bone.quaternion.copy(n.bone.parent.getWorldQuaternion(this.delta).invert().multiply(this.world));
      n.bone.updateMatrixWorld(true);
    }
    this.steps++;
  }

  snapshot() {
    return {active:this.active,engine:'骨骼布料/PBD',particles:this.nodes.length,links:this.edges.length,steps:this.steps,
      max_displacement:Math.max(0,...this.nodes.map(n=>n.point.distanceTo(n.target))),
      min_free_y:Math.min(...this.nodes.filter(n=>!n.root).map(n=>n.point.y)),
      floor:this.floor};
  }
}
