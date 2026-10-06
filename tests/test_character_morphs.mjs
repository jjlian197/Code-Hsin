import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';
import {HsinBehavior} from '../src/assets/pmx_viewer/behavior.js';
import {validateMorphMap,mappedMorphNames} from '../src/assets/pmx_viewer/rig/morphs.js';

const profile=JSON.parse(fs.readFileSync('src/assets/character_profiles/aemeath.json','utf8'));
const names=mappedMorphNames(profile),mesh={skeleton:{bones:[]},morphTargetDictionary:Object.fromEntries(names.map((n,i)=>[n,i])),morphTargetInfluences:names.map(()=>0)};
validateMorphMap(profile,names);
assert.throws(()=>validateMorphMap(profile,names.filter(n=>n!=='垂れ目')),/别名/);
const bad=structuredClone(profile);bad.expressions.happy['にこり']=NaN;
assert.throws(()=>validateMorphMap(bad,names),/权重/);
const behavior=new HsinBehavior(mesh,{auto_blink:false,breathing:false,random_idle:false},()=>.5,null,profile);
const value=name=>mesh.morphTargetInfluences[mesh.morphTargetDictionary[name]];
behavior.setExpression('happy');behavior.advance(.1);behavior.applyFace();
assert.equal(value('にこり'),.65);assert.equal(value('左口角上げ'),.25);
behavior.prepareFrame();behavior.setExpression('normal');behavior.setPointer(1,0,true);behavior.advance(1);behavior.applyFace();
assert(value('left')>.5);assert.equal(value('にこり'),0,'表情退出恢复');
for(const [vowel,morph] of Object.entries({a:'あ',i:'い',u:'う',e:'え',o:'お'})){
  behavior.prepareFrame();behavior.setLip(.8,vowel,500);behavior.advance(.1);behavior.applyFace();
  assert(value(morph)>.5);for(const other of ['あ','い','う','え','お'].filter(n=>n!==morph))assert.equal(value(other),0,'五元音不能残留');
}
behavior.prepareFrame();behavior.setLip(0,'a',0);behavior.advance(1);behavior.applyFace();assert(value('お')===0);
console.log('PASS 角色表情别名、真实方向通道、表情释放、五元音切换与非法映射');
