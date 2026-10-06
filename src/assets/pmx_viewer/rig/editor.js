import {matchRig} from './matcher.js';

// 校正与命令行共用匹配器；失败时保持上一次有效修正。
export class RigEditor {
  constructor(report) {
    this.model = report.model;
    this.data = {bones:report.skeleton.map(b => ({...b, fixAxis:b.fixedAxis,
      localXVector:b.localAxes?.x, localZVector:b.localAxes?.z})),
      rigidBodies:report.skeleton.filter(b=>b.category==='physics').map(b=>({boneIndex:b.index}))};
    this.overrides = {modelSha256:this.model.sha256, bones:Object.fromEntries(Object.entries(report.bones)
      .filter(([,m])=>['manual','disabled'].includes(m.status)).map(([id,m])=>[id,m.status==='disabled'?null:m.index]))};
    this.report = report;
  }
  apply(overrides) {
    const next = matchRig(this.data,this.model,overrides);
    this.overrides = {modelSha256:this.model.sha256, bones:{...overrides.bones}};
    this.report = next;
    return next;
  }
  set(id, index) {return this.apply({...this.overrides,bones:{...this.overrides.bones,[id]:index}});}
  reset(id) {
    const bones = {...this.overrides.bones};delete bones[id];
    return this.apply({...this.overrides,bones});
  }
  export() {return JSON.stringify(this.overrides,null,2)+'\n';}
}
