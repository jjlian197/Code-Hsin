// 多辅助刚体的果冻胸结构在 Bullet 下有持续上托；只适配该结构，不改原始 PMX。
export function adaptChestPhysics(mesh) {
  const mmd=mesh.geometry.userData.MMD;
  const removed=new Set(), replacements=new Map();
  for(const side of ['右','左']){
    const name=side+'胸';
    const main=mmd.rigidBodies.findIndex(b=>b.name===name&&b.type===1&&mesh.skeleton.bones[b.boneIndex]?.name===name);
    const auxiliaries=mmd.rigidBodies.map((b,i)=>({b,i})).filter(({b})=>b.boneIndex===-1&&b.name.startsWith(name+'_'));
    const lifted=mmd.constraints.some(c=>auxiliaries.some(({i})=>i===c.rigidBodyIndex1||i===c.rigidBodyIndex2)
      &&c.translationLimitation1[1]>0&&c.translationLimitation1[1]===c.translationLimitation2[1]);
    const anchor=mmd.constraints.find(c=>c.name===name&&c.rigidBodyIndex2===main
      &&mmd.rigidBodies[c.rigidBodyIndex1].type===0);
    if(main<0||auxiliaries.length<4||!lifted||!anchor)continue;
    auxiliaries.forEach(({i})=>removed.add(i));
    // 位置跟随胸部骨骼，保留受限旋转；避免刚体把蒙皮胸部整体平移抬高。
    mmd.rigidBodies[main]={...mmd.rigidBodies[main],type:2};
    replacements.set(anchor,{...anchor,translationLimitation1:[0,0,0],translationLimitation2:[0,0,0],
      rotationLimitation1:[-.12,-.12,-.08],rotationLimitation2:[.12,.12,.08],springRotation:[8,8,8]});
  }
  if(!removed.size)return;
  const indices=new Map();
  mmd.rigidBodies=mmd.rigidBodies.filter((b,i)=>{if(removed.has(i))return false;indices.set(i,indices.size);return true;});
  mmd.constraints=mmd.constraints.filter(c=>!removed.has(c.rigidBodyIndex1)&&!removed.has(c.rigidBodyIndex2))
    .map(c=>({...replacements.get(c)||c,rigidBodyIndex1:indices.get(c.rigidBodyIndex1),rigidBodyIndex2:indices.get(c.rigidBodyIndex2)}));
}
