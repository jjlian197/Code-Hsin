// 为求解器提供末端骨别名，保留真实骨名与 IK/Grant/动画绑定。
export function gestureBones(mesh){
  const bones=new Map(mesh.skeleton.bones.map(b=>[b.name,b]));
  for(const side of ['右','左'])for(const finger of ['親','人','中','薬','小']){
    const name=side+finger+'指先';
    const actual=bones.get(side+finger+'指'+(finger==='親'?'２':'３')+'先');
    if(!bones.has(name)&&actual)bones.set(name,actual);
  }
  return bones;
}
