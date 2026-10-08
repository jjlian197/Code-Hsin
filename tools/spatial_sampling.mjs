import * as THREE from '../src/assets/pmx_viewer/lib/three/three.module.js';

// PMX coordinates remain unchanged during sampling; the exporter receives scaled copies.
export function createSpatialMesh(model) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(model.vertices.flatMap(vertex => vertex.position), 3));
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(model.vertices.flatMap(vertex => [...vertex.skinIndices, 0, 0, 0, 0].slice(0, 4)), 4));
  geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(model.vertices.flatMap(vertex => [...vertex.skinWeights, 0, 0, 0, 0].slice(0, 4)), 4));
  geometry.userData.MMD = {rigidBodies: model.rigidBodies, constraints: model.constraints,
    grants: model.bones.flatMap((bone, index) => bone.grant ? [{index, ...bone.grant, transformationClass: bone.transformationClass}] : [])
      .sort((left, right) => left.transformationClass - right.transformationClass || left.index - right.index)};
  const mesh = new THREE.SkinnedMesh(geometry);
  const bones = model.bones.map(source => {
    const bone = new THREE.Bone();
    bone.name = source.name;
    bone.position.fromArray(source.position);
    if (source.parentIndex >= 0) bone.position.sub(new THREE.Vector3().fromArray(model.bones[source.parentIndex].position));
    return bone;
  });
  bones.forEach((bone, index) => (model.bones[index].parentIndex >= 0 ? bones[model.bones[index].parentIndex] : mesh).add(bone));
  mesh.bind(new THREE.Skeleton(bones));
  mesh.updateMatrixWorld(true);
  return mesh;
}

export function boneChannels(mesh, scale) {
  return mesh.skeleton.bones.map((bone, index) => [index, ...bone.position.toArray().map(value => value * scale), ...bone.quaternion.toArray()]);
}
