import * as THREE from 'three';

export const expressions = {
  normal: {}, happy: {'にこり':0.65,'口角上げ左':0.25,'口角上げ右':0.25},
  sad: {'困る':0.7,'悲しい目':0.5}, angry:{'怒り':0.7},
  surprised:{'びっくり':0.65,'お':0.2}, wink:{'ウィンク':1}, sleepy:{'まばたき':0.7},
  relaxed:{'たれ目':0.3,'にこり２':0.3}, blush:{'FaceRed':0.8,'照れ':0.65,'にこり':0.25},
  content:{'笑い':0.8,'にこり':0.55,'口角上げ左':0.25,'口角上げ右':0.25},
  star_eyes:{'星目':1,'星目2':1}, heart_eyes:{'はぁと':1,'はぁと2':1},
};
const vowels = {a:'あ',i:'い',u:'う',e:'え',o:'お'};
export const behaviorMorphNames = [...new Set([
  ...Object.values(expressions).flatMap(v=>Object.keys(v)), ...Object.values(vowels),
  'Left','Right','Up','Down','ウィンク右','笑い','口角下げ左','口角下げ右','真面目',
])];
const clamp = (v,a=0,b=1)=>Math.min(b,Math.max(a,v));
const smooth = (v,target,speed,delta)=>v+(target-v)*(1-Math.exp(-speed*delta));
const radians = v=>v*Math.PI/180;

export class HsinBehavior {
  constructor(mesh,options={},random=Math.random) {
    this.mesh=mesh;this.random=random;this.time=0;
    this.settings={auto_blink:true,breathing:true,mouse_follow:true,touch_reactions:true,conversation_actions:true,random_idle:true,...options};
    this.parameters={};this.expression='normal';this.pointer={x:0,y:0};this.manualLook=false;this.gaze={x:0,y:0};
    this.bones=new Map(mesh.skeleton.bones.map(b=>[b.name,b]));
    this.boneBases=new Map();this.morphBases=new Map();this.ownedBones=new Set();this.ownedMorphs=new Set();
    this.blinkStart=null;this.nextBlink=2.0+this.random()*2;this.blink=0;this.breath=0;
    this.audio={value:0,active:false};this.lip={value:0,shape:'a',until:0};
    this.touchState=null;this.lastTouch=null;this.touchWeight=0;this.mouthOpen=0;this.mouthShape='a';
    this.offsetQuaternion=new THREE.Quaternion();this.offsetEuler=new THREE.Euler();
    this.activity={state:'idle',interacting:false};this.manualMotion=false;
    this.activityWeights={thinking:0,speaking:0,listening:0};
    this.idleAction=null;this.idleWeight=0;this.nextIdle=this.time+18+this.random()*27;
  }

  setExpression(name) { if(!(name in expressions))return false;this.expression=name;return true; }
  setParameters(params) { Object.assign(this.parameters,params); }
  clearParameters() { this.parameters={}; }
  setPointer(x,y,manual=false) { this.pointer={x:clamp(x,-1,1),y:clamp(y,-1,1)};this.manualLook=manual; }
  setAudio(value,active) { this.audio={value:clamp(value),active}; }
  setLip(value,shape='a',duration=0.25) { this.lip={value:clamp(value),shape,until:this.time+duration}; }
  setSettings(settings) { Object.assign(this.settings,settings); }
  setActivity(activity) {
    if(!['idle','thinking','speaking','listening'].includes(activity.state))return false;
    this.activity={state:activity.state,interacting:!!activity.interacting};return true;
  }
  setManualMotion(active) { this.manualMotion=active;if(active)this.cancelIdle(); }
  cancelIdle() { this.idleAction=null;this.idleWeight=0;this.nextIdle=this.time+18+this.random()*27; }
  suspend() { this.cancelIdle(); }
  forceBlink() { this.blinkStart=this.time; }

  setMotionClip(clip) {
    this.ownedBones.clear();this.ownedMorphs.clear();
    for(const track of clip?.tracks||[]) {
      const bone=/\.bones\[(.*?)\]\.(quaternion|position)/.exec(track.name);
      const morph=/morphTargetInfluences\[(\d+)\]/.exec(track.name);
      if(bone)this.ownedBones.add(bone[1]+'.'+bone[2]);
      if(morph)this.ownedMorphs.add(Number(morph[1]));
    }
  }

  touch(part) {
    if(!this.settings.touch_reactions || (this.lastTouch && this.time-this.lastTouch.time<0.45))return false;
    this.lastTouch={part,time:this.time};this.touchState={part,start:this.time};this.forceBlink();return true;
  }

  advance(delta) {
    this.time+=delta;
    if(!this.settings.auto_blink && this.blinkStart===null)this.blink=0;
    if(this.settings.auto_blink && this.blinkStart===null && this.time>=this.nextBlink)this.forceBlink();
    if(this.blinkStart!==null) {
      const t=this.time-this.blinkStart;
      this.blink=t<0.06?clamp(t/0.06):t<0.085?1:clamp(1-(t-0.085)/0.105);
      if(t>=0.19){this.blinkStart=null;this.blink=0;this.nextBlink=this.time+2.6+this.random()*3.4;}
    }
    const target=this.settings.mouse_follow||this.manualLook?this.pointer:{x:0,y:0};
    this.gaze.x=smooth(this.gaze.x,this.parameters.ParamEyeBallX??target.x,8,delta);
    this.gaze.y=smooth(this.gaze.y,this.parameters.ParamEyeBallY??target.y,8,delta);
    this.breath=this.settings.breathing?Math.sin(this.time*2*Math.PI/4.7):0;
    this.touchWeight=this.touchState?Math.sin(Math.PI*clamp((this.time-this.touchState.start)/1.8)):0;
    if(this.touchState && this.time-this.touchState.start>=1.8)this.touchState=null;
    const lipActive=this.lip.until>this.time;
    const targetMouth=this.audio.active?this.audio.value:lipActive?this.lip.value:(this.parameters.ParamMouthOpenY??0);
    this.mouthOpen=smooth(this.mouthOpen,targetMouth,targetMouth>this.mouthOpen?22:14,delta);
    this.mouthShape=lipActive?this.lip.shape:'a';
    const occupied=this.manualMotion||this.activity.interacting||!!this.touchState;
    for(const state of Object.keys(this.activityWeights)) {
      const target=this.settings.conversation_actions&&!occupied&&this.activity.state===state?1:0;
      this.activityWeights[state]=smooth(this.activityWeights[state],target,6,delta);
    }
    const fixedLook=this.manualLook||['ParamAngleX','ParamAngleY','ParamAngleZ','ParamEyeBallX','ParamEyeBallY'].some(p=>p in this.parameters);
    const eligible=this.settings.random_idle&&!occupied&&!fixedLook&&this.activity.state==='idle'&&!this.audio.active;
    if(!eligible) { if(this.idleAction)this.cancelIdle();this.nextIdle=this.time+18+this.random()*27; }
    else if(this.idleAction) {
      const progress=(this.time-this.idleAction.start)/this.idleAction.duration;
      this.idleWeight=Math.sin(Math.PI*clamp(progress))**2;
      if(progress>=1)this.cancelIdle();
    }else if(this.time>=this.nextIdle) {
      this.idleAction={name:this.random()<0.6?'look_around':'stretch',start:this.time,duration:5.5};
    }
  }

  prepareFrame() {
    // 在下一次 mixer/物理更新前恢复底层值，叠加层不会逐帧积累。
    for(const [bone,base] of this.boneBases){bone.quaternion.copy(base.quaternion);bone.position.copy(base.position);}
    for(const [index,value] of this.morphBases)this.mesh.morphTargetInfluences[index]=value;
    this.boneBases.clear();this.morphBases.clear();
  }

  rotate(name,x=0,y=0,z=0) {
    const bone=this.bones.get(name);
    if(!bone || this.ownedBones.has(name+'.quaternion'))return;
    if(!this.boneBases.has(bone))this.boneBases.set(bone,{quaternion:bone.quaternion.clone(),position:bone.position.clone()});
    bone.quaternion.multiply(this.offsetQuaternion.setFromEuler(this.offsetEuler.set(x,y,z)));
  }

  applyBones() {
    const target=this.settings.mouse_follow||this.manualLook?this.gaze:{x:0,y:0};
    const yaw=radians(this.parameters.ParamAngleX??target.x*22);
    const pitch=radians(this.parameters.ParamAngleY??-target.y*12);
    const roll=radians(this.parameters.ParamAngleZ??0);
    const bodyX=radians(this.parameters.ParamBodyAngleX??0), bodyY=radians(this.parameters.ParamBodyAngleY??0);
    this.rotate('首',pitch*0.2,yaw*0.2,roll*0.2);
    this.rotate('頭',pitch*0.8,yaw*0.8,roll*0.8+(this.touchState?.part==='head'?0.07*this.touchWeight:0));
    this.rotate('上半身',this.breath*0.009+bodyY,bodyX,0);
    this.rotate('上半身2',this.breath*0.008,0,this.touchState?.part==='body'?0.025*this.touchWeight:0);
    // 手动动作、VMD、拖动与触摸优先，自动姿态不会改写它们。
    if(!this.manualMotion&&!this.activity.interacting&&!this.touchState) {
      const {thinking,speaking,listening}=this.activityWeights;
      this.rotate('頭',thinking*0.05-listening*0.035,thinking*0.1,listening*-0.09);
      this.rotate('上半身2',-listening*0.025,0,speaking*0.012*Math.sin(this.time*1.6));
      this.rotate('右腕',0,-thinking*0.045,-speaking*(0.12+0.025*Math.sin(this.time*2)));
      this.rotate('右ひじ',-speaking*0.13,0,-thinking*0.08-speaking*0.06);
      this.rotate('右手首',0,speaking*0.06*Math.sin(this.time*1.7),0);
      if(this.idleAction) {
        const w=this.idleWeight;
        if(this.idleAction.name==='look_around')this.rotate('頭',0,0.24*Math.sin((this.time-this.idleAction.start)*1.5)*w,0.025*w);
        else {
          this.rotate('上半身2',-0.045*w,0,0);this.rotate('頭',-0.05*w,0,0);
          this.rotate('右肩',0,0,-0.06*w);this.rotate('左肩',0,0,0.06*w);
          this.rotate('右腕',0,0,-0.32*w);this.rotate('左腕',0,0,0.32*w);
        }
      }
    }
    const torso=this.bones.get('上半身');
    if(torso&&!this.ownedBones.has('上半身.position')) {
      if(!this.boneBases.has(torso))this.boneBases.set(torso,{quaternion:torso.quaternion.clone(),position:torso.position.clone()});
      torso.position.y+=this.breath*0.05;
    }
  }

  morph(name,value) {
    const index=this.mesh.morphTargetDictionary[name];
    if(index===undefined || this.ownedMorphs.has(index))return;
    if(!this.morphBases.has(index))this.morphBases.set(index,this.mesh.morphTargetInfluences[index]);
    this.mesh.morphTargetInfluences[index]=Math.max(this.mesh.morphTargetInfluences[index],clamp(value));
  }

  applyFace() {
    for(const [name,value] of Object.entries(expressions[this.expression]))this.morph(name,value);
    const p=this.parameters;
    const left=1-(p.ParamEyeLOpen??1),right=1-(p.ParamEyeROpen??1);
    const closure=Math.max(this.blink,Math.min(left,right));
    if(this.expression==='wink') {
      // 已闭合的一侧不再叠加双眼眨眼，避免眼睑超量变形。
      this.morph('ウィンク右',Math.max(closure,right));
    }else {
      this.morph('まばたき',closure*(this.expression==='content'?0.2:1));
      this.morph('ウィンク',Math.max(0,left-closure));this.morph('ウィンク右',Math.max(0,right-closure));
    }
    // 模型的 Left 在 Three.js 正面相机中向屏幕右移动，已核对 PMX 顶点位移。
    this.morph('Left',Math.max(0,this.gaze.x)*0.55);this.morph('Right',Math.max(0,-this.gaze.x)*0.55);
    this.morph('Up',Math.max(0,this.gaze.y)*0.45);this.morph('Down',Math.max(0,-this.gaze.y)*0.45);
    this.morph(vowels[this.mouthShape]||vowels.a,this.mouthOpen*0.85);
    const smile=p.ParamMouthForm??0;
    this.morph('口角上げ左',Math.max(smile,0)*0.5);this.morph('口角上げ右',Math.max(smile,0)*0.5);
    this.morph('口角下げ左',Math.max(-smile,0)*0.5);this.morph('口角下げ右',Math.max(-smile,0)*0.5);
    if(this.expression==='normal'&&!this.manualMotion&&!this.activity.interacting&&!this.touchState) {
      this.morph('真面目',this.activityWeights.thinking*0.18);
      this.morph('にこり',this.activityWeights.speaking*0.15);
      this.morph('たれ目',this.activityWeights.listening*0.14);
    }
    if(this.touchState) {
      if(this.touchState.part==='tail'){this.morph('びっくり',this.touchWeight*0.3);this.morph('お',this.touchWeight*0.25);}
      else {this.morph('にこり',this.touchWeight*0.5);this.morph('口角上げ左',this.touchWeight*0.4);this.morph('口角上げ右',this.touchWeight*0.4);}
    }
  }

  snapshot() {
    const morphs={};for(const name of behaviorMorphNames){const index=this.mesh.morphTargetDictionary[name];if(index!==undefined)morphs[name]=this.mesh.morphTargetInfluences[index];}
    return {settings:{...this.settings},expression:this.expression,gaze:{...this.gaze},pointer:{...this.pointer},
      blink:this.blink,breath:this.breath,mouth_open:this.mouthOpen,mouth_shape:this.mouthShape,audio_driven:this.audio.active,
      parameters:{...this.parameters},last_touch:this.lastTouch,touch_active:!!this.touchState,
      activity:{...this.activity},activity_weights:{...this.activityWeights},manual_motion:this.manualMotion,
      idle_action:this.idleAction?.name||null,idle_weight:this.idleWeight,next_idle:this.nextIdle,morphs};
  }
}
