// Node 检查复用网页 import map 的本地 Three.js，无需安装第二份依赖。
export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'three') return {url: new URL('../src/assets/pmx_viewer/lib/three/three.module.js', import.meta.url).href, shortCircuit:true};
  return nextResolve(specifier, context);
}
