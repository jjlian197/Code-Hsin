import * as THREE from 'three';

// 骨骼布料之外的最后一层显示约束，防止未被骨骼覆盖的衣发边缘穿过地面。
// 身体、皮肤、眼睛和鞋底仍由动作骨骼支撑；顶点投影本身不算物理碰撞。
export const groundedMaterial = name => !/Skin|^Hand|Glove|^Face|^Eye|Nail/.test(name);

export function installGroundSupport(mesh) {
  const floor={value:0}, enabled={value:0};
  for(const material of mesh.material){
    if(!groundedMaterial(material.name))continue;
    const compile=material.onBeforeCompile;
    material.onBeforeCompile=shader=>{
      compile?.(shader);
      shader.uniforms.hsinFloor=floor;shader.uniforms.hsinGround=enabled;
      shader.vertexShader='uniform float hsinFloor;\nuniform float hsinGround;\n'+shader.vertexShader;
      shader.vertexShader=shader.vertexShader.replace('#include <skinning_vertex>',
        '#include <skinning_vertex>\ntransformed.y = mix(transformed.y, max(transformed.y, hsinFloor + 0.035), hsinGround);');
    };
    material.customProgramCacheKey=()=> 'hsin-ground-support-v1';material.needsUpdate=true;
  }
  mesh.userData.groundSupport={floor,enabled};
}

export function setGroundSupport(mesh, floor, active) {
  const support=mesh.userData.groundSupport;
  if(support){support.floor.value=floor;support.enabled.value=active?1:0;}
}

export function visibleBounds(mesh) {
  mesh.updateMatrixWorld(true);mesh.skeleton.update();
  const support=mesh.userData.groundSupport;
  if(!support?.enabled.value){mesh.computeBoundingBox();return mesh.boundingBox.clone();}
  const box=new THREE.Box3(),p=new THREE.Vector3(),index=mesh.geometry.index;
  // 按实际材质复现顶点着色器的落地约束，用于取景检查。
  for(const group of mesh.geometry.groups){
    const ground=groundedMaterial(mesh.material[group.materialIndex].name);
    const seen=new Set();
    for(let i=group.start;i<group.start+group.count;i++){
      const vertex=index?index.getX(i):i;if(seen.has(vertex))continue;seen.add(vertex);
      mesh.getVertexPosition(vertex,p);
      if(ground)p.y=Math.max(p.y,support.floor.value+.035);
      box.expandByPoint(p);
    }
  }
  return box;
}
