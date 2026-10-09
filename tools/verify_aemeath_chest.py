"""爱弥斯原版、改骨与补偿对照；隔离窗口，不保存角色状态或启动语音服务。"""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import traceback

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel
from src.core import app_config
from src.core.pmx_view import PmxView
from tools.verify_behavior import GuiProbe

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    folder = ROOT / ".runtime/aemeath-chest"
    package = json.loads((ROOT / ".runtime/characters/aemeath/character.json").read_text(encoding="utf8"))
    source = Path(package["model"]["path"])
    patched = folder / "model/爱弥斯_胸骨改绑_物理后.pmx"
    running = json.loads((ROOT / ".runtime/rig-aemeath/running.json").read_text(encoding="utf8"))
    private_root = folder / "viewer-root"
    target = private_root / "src/assets/pmx_viewer"
    shutil.copytree(ROOT / "src/assets/pmx_viewer", target, dirs_exist_ok=True)
    shutil.copytree(ROOT / "src/assets/motions", target.parent / "motions", dirs_exist_ok=True)
    viewer = target / "viewer.js"
    viewer.write_text(viewer.read_text(encoding="utf8").replace(
        "applyAemeathChestRig(data,options.model_hash)", "(window.__aemeathNative?0:applyAemeathChestRig(data,options.model_hash))") + """
window.HsinPmxDebug.chestState=()=>({
  finite:mesh.skeleton.bones.every(b=>[...b.position,...b.quaternion].every(Number.isFinite)),
  bones:mesh.skeleton.bones.filter(b=>/^[左右]胸/.test(b.name)).map(b=>({name:b.name,parent:b.parent.name,
    position:b.position.toArray(),rotation:b.quaternion.toArray(),world:b.getWorldPosition(new THREE.Vector3()).toArray()})),
  types:runtime.physics.bodies.filter(b=>/^[左右]胸/.test(b.params.name)).map(b=>b.params.type)
});
window.HsinPmxDebug.runChestTrial=data=>{runtime.clips.treadmill_running=runningClip(data,mesh);runtime.play('treadmill_running');};
""", encoding="utf8")
    runtime = target / "animation_runtime.js"
    runtime.write_text(runtime.read_text(encoding="utf8").replace(
        "adaptAemeathChestPhysics(mesh,options.model_hash)", "(window.__aemeathNative?0:adaptAemeathChestPhysics(mesh,options.model_hash))"), encoding="utf8")
    app_config.PROJECT_ROOT = private_root
    app_config.RESOURCE_ROOT = ROOT
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["Aemeath chest preview"])
    app.setQuitOnLastWindowClosed(False)
    window = QWidget()
    window.setWindowTitle("爱弥斯 · 改骨与胸部补偿对照")
    window.resize(850, 800)
    layout = QVBoxLayout(window)
    bar = QHBoxLayout()
    layout.addLayout(bar)
    choice = QComboBox()
    variants = [("原版原生", source, True), ("仅改骨", patched, True), ("原版自动改骨 + 补偿", source, False), ("改骨副本 + 补偿", patched, False)]
    choice.addItems([v[0] for v in variants])
    choice.setCurrentIndex(2)
    bar.addWidget(choice)
    restart = QPushButton("重播半速跑步")
    bar.addWidget(restart)
    status = QLabel("加载中…")
    layout.addWidget(status)
    view = PmxView(source, window, animation_config={"physics": True, "behavior": dict.fromkeys(
        ("auto_blink", "breathing", "mouse_follow", "touch_reactions", "conversation_actions", "random_idle"), False)})
    window.sprite_view = view
    layout.addWidget(view)
    probe = GuiProbe(window)
    pool = ThreadPoolExecutor(1)
    report = {"success": False, "variants": [], "failures": []}

    async def gui(fn):
        return await probe.call(lambda f: f.set_result(fn()))

    async def load(index, character=False):
        label, model, native = variants[index]
        await probe.evaluate("window.__aemeathNative=" + str(native).lower() + ";")
        await gui(lambda: view.load_character(ROOT / '.runtime/characters/aemeath/character.json') if character else view.load_default_model(model))
        for _ in range(500):
            assert not await gui(lambda: view.load_error), view.load_error
            if await gui(lambda: view.model_loaded):
                break
            await asyncio.sleep(.1)
        else:
            raise AssertionError("爱弥斯加载超时")
        await gui(lambda: view.frame_timer.stop())
        await probe.evaluate("window.__aemeathClock=performance.now();window.HsinPmx.tick(window.__aemeathClock);")
        return await gui(lambda: view.model_info)

    async def verify():
        for _ in range(500):
            if await gui(lambda: view._ready):
                break
            await asyncio.sleep(.1)
        for index, (label, model, native) in enumerate(variants):
            info = await load(index)
            assert info["texture_errors"] == 0
            assert info["runtime"]["chest_compensated_bodies"] == (0 if native else 6)
            assert info["chest_rig_bones"] == (0 if native else 10)
            await probe.evaluate("window.HsinPmxDebug.runChestTrial(" + json.dumps(running) + ");")
            samples = json.loads(await probe.evaluate("""JSON.stringify((()=>{
              const out=[];for(let i=0;i<470;i++){
                window.HsinPmx.tick(window.__aemeathClock+=1000/30);
                if(i%10===0)out.push(window.HsinPmxDebug.chestState());
              }return out;
            })());"""))
            assert all(s["finite"] for s in samples)
            assert (await probe.state())["motion"] == "treadmill_running"
            if not native:
                assert all(t == 2 for t in samples[-1]["types"])
                drift = max(abs(a-b) for s in samples for bone in s["bones"] for a,b in zip(bone["position"], samples[0]["bones"][[b["name"] for b in s["bones"]].index(bone["name"])]["position"]))
                assert drift < .03, drift
            else:
                drift = None
            rotations = [s["bones"][0]["rotation"] for s in samples]
            variation = max(sum((a-b)**2 for a,b in zip(q, rotations[0]))**.5 for q in rotations)
            assert variation > 1e-4, "胸部动态未推进"
            dest = folder / f"preview-{index}.png"
            await gui(lambda: view.grab().save(str(dest)))
            await probe.evaluate("window.HsinPmx.playMotion('idle');window.HsinPmx.setPhysics(false);")
            off = json.loads(await probe.evaluate("""JSON.stringify((()=>{
              const out=[];for(let i=0;i<30;i++){window.HsinPmx.tick(window.__aemeathClock+=1000/30);out.push(window.HsinPmxDebug.chestState());}return out;
            })());"""))
            assert all(s["finite"] for s in off)
            assert off[0]["bones"] == off[-1]["bones"], "关闭物理后胸骨仍在变化"
            report["variants"].append({"label": label, "model": str(model), "compensated_bodies": 0 if native else 6,
                "max_local_position_drift": drift, "rotation_variation": variation, "capture": str(dest), "samples": samples})
            print("PASS:", label, "半速跑步、有限骨骼、动态与物理开关", flush=True)
        info = await load(2, character=True)
        assert info['character'] == '爱弥斯' and len(info['expressions']) == 12
        assert info['motions'] == ['idle', 'nod', 'wave', 'peace', 'finger_heart', 'crossed_arms', 'treadmill_running']
        assert info['runtime']['chest_compensated_bodies'] == 6
        for expression in ('normal', 'happy', 'star_eyes', 'heart_eyes'):
            assert await probe.evaluate(f"window.HsinPmx.setExpression('{expression}');")
        for shape, morph in {'a': 'あ', 'i': 'い', 'u': 'う', 'e': 'え', 'o': 'お'}.items():
            await probe.evaluate(f"window.HsinPmx.setLipSync(.8,'{shape}',500);for(let i=0;i<4;i++)window.HsinPmx.tick(window.__aemeathClock+=1000/30);")
            assert (await probe.state())['behavior']['morphs'][morph] > .5
        report['character_package'] = {'expressions': 12, 'vowels': 5, 'compensated_bodies': 6}
        report["success"] = True

    def select():
        if view._ready:
            label, model, native = variants[choice.currentIndex()]
            view.web.page().runJavaScript("window.__aemeathNative=" + str(native).lower() + ";", lambda _: view.load_default_model(model))

    def play():
        if view.model_loaded:
            view.web.page().runJavaScript("window.HsinPmxDebug.runChestTrial(" + json.dumps(running) + ");")

    ready_once = False

    def loaded(success):
        nonlocal ready_once
        if not success:
            status.setText(view.load_error or "加载失败")
            return
        if not args.verify:
            if not ready_once:
                ready_once = True
                select()
                return
            status.setText(choice.currentText() + "；胸部补偿启用时使用六个受限旋转刚体")
            view.web.page().runJavaScript("window.HsinPmxDebug.view(0);")
            play()

    choice.currentIndexChanged.connect(lambda _: select())
    restart.clicked.connect(play)
    view.load_finished.connect(loaded)
    window.show()
    if args.verify:
        future = pool.submit(lambda: asyncio.run(verify()))

        def watch():
            if future.done():
                try:
                    future.result()
                except Exception:
                    report["failures"].append(traceback.format_exc())
                app.quit()
            else:
                QTimer.singleShot(50, watch)
        watch()
        QTimer.singleShot(180000, app.quit)
    else:
        app.setQuitOnLastWindowClosed(True)
    try:
        app.exec()
    finally:
        view.cleanup()
        window.hide()
        pool.shutdown(wait=True)
    if args.verify:
        (folder / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
        print(json.dumps({"success": report["success"], "variants": len(report["variants"]), "failures": report["failures"]}, ensure_ascii=False))
        return 0 if report["success"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
