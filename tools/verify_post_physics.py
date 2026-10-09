"""仅本机 PMX 副本实验；独立窗口，不保存日常配置，不运行语音或聊天。"""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PyQt6.QtCore import Qt,QTimer
from PyQt6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QCheckBox,QPushButton,QLabel
from PyQt6.QtGui import QColor
from src.core import app_config
from src.core.pmx_view import PmxView

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');parser.add_argument('--running',action='store_true');parser.add_argument('--trial-dir',default=str(ROOT/'.runtime/pmx-physics-trial'));args=parser.parse_args()
    folder=Path(args.trial_dir).resolve()
    report=json.loads((folder/'patch-report.json').read_text(encoding='utf8'))
    original_config=app_config.load_config()
    private_root=folder/'viewer-root'
    target=private_root/'src/assets/pmx_viewer'
    shutil.copytree(ROOT/'src/assets/pmx_viewer',target,dirs_exist_ok=True)
    runtime=target/'animation_runtime.js'
    runtime.write_text(runtime.read_text(encoding='utf8').replace('adaptChestPhysics(mesh);','if (!window.__nativeChestTrial) adaptChestPhysics(mesh);'),encoding='utf8')
    viewer=target/'viewer.js'
    # 对照窗口保留原版；日常播放器的默认改骨不能污染实验分组。
    viewer.write_text(viewer.read_text(encoding='utf8').replace(
        'const chestRigBones=applyHsinChestRig(data,options.model_hash)||applyAemeathChestRig(data,options.model_hash);', 'const chestRigBones=0;'),encoding='utf8')
    shutil.copytree(ROOT/'src/assets/motions',target.parent/'motions',dirs_exist_ok=True)
    viewer.write_text(viewer.read_text(encoding='utf8')+"\nwindow.HsinPmxDebug.trialChest=()=>{if(!mesh)return null;mesh.updateMatrixWorld(true);return mesh.skeleton.bones.map((b,i)=>({index:i,name:b.name,parent:b.parent?.name,position:b.getWorldPosition(new THREE.Vector3()).toArray(),rotation:b.quaternion.toArray()})).filter(b=>/^(左右胸|左胸|右胸|ZSpring_Spine_)/.test(b.name));};\n",encoding='utf8')
    if args.running:viewer.write_text(viewer.read_text(encoding='utf8')+'\n'+(ROOT/'tools/rig/post_physics_preview.js').read_text(encoding='utf8'),encoding='utf8')
    app_config.PROJECT_ROOT=private_root
    app_config.RESOURCE_ROOT=ROOT
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app=QApplication(['Hsin PMX physics trial'])
    app.setQuitOnLastWindowClosed(True)
    window=QWidget();window.setWindowTitle('心 · 胸部辅助骨试验（隔离预览）');window.resize(800,850)
    layout=QVBoxLayout(window);bar=QHBoxLayout();layout.addLayout(bar)
    choice=QComboBox();bar.addWidget(choice)
    models={};textures={}
    for item in report['changes']:
        name='一阶段' if item['form']=='first' else '二阶段'
        for variant in ('source','output'):
            label=name+(' · 原模型' if variant=='source' else ' · 改绑 + 物理后副本')
            models[label]=Path(item[variant]);choice.addItem(label)
            textures[item[variant]]=original_config['sprite']['model'].get('texture_overrides',{}).get(item['form'],{})
    physics=QCheckBox('物理');physics.setChecked(True);bar.addWidget(physics)
    native=QCheckBox('原生胸物理（实验）');native.setChecked(args.verify);bar.addWidget(native)
    reset=QPushButton('重置物理');bar.addWidget(reset)
    closeup=QPushButton('近景');closeup.setCheckable(True);closeup.setChecked(not args.verify);bar.addWidget(closeup)
    note=QLabel('推荐改绑副本 + 关闭原生胸物理，使用现有胸部补偿。“原生胸物理”勾选后跳过补偿，供对比。')
    note.setWordWrap(True);layout.addWidget(note)
    status=QLabel('加载中…');layout.addWidget(status)
    view=PmxView(next(iter(models.values())),window,texture_overrides=textures,animation_config={'physics':True,'behavior':{'auto_blink':True,'breathing':True,'mouse_follow':False,'touch_reactions':False,'conversation_actions':False,'random_idle':False}})
    view.web.page().setBackgroundColor(QColor('#292733'));layout.addWidget(view,1)
    errors=[];results=[];labels=list(models);index=0;ready_once=False;busy=False;samples=[];sample_busy=False
    def select():
        if not view._ready:return
        status.setText('加载中…')
        view.web.page().runJavaScript('window.__nativeChestTrial='+str(native.isChecked()).lower()+';',lambda _:view.load_default_model(models[choice.currentText()]))
    choice.currentTextChanged.connect(lambda _:select());native.toggled.connect(lambda _:select())
    physics.toggled.connect(lambda enabled:view.set_physics(enabled));reset.clicked.connect(view.reset_physics)
    def camera():
        view.web.page().runJavaScript('window.HsinPmxDebug.view(0);' if closeup.isChecked() else 'window.HsinPmxDebug.resetView();')
    closeup.toggled.connect(lambda _:camera())
    def loaded(success):
        nonlocal ready_once,busy
        if not success:
            if view.load_error:errors.append(view.load_error)
            status.setText(view.load_error or '模型加载失败')
            if args.verify:app.quit()
            return
        if not ready_once:
            ready_once=True;select();return
        status.setText(choice.currentText()+'；贴图错误 '+str(view.model_info.get('texture_errors')))
        camera()
        if args.running:
            form='first' if choice.currentIndex()<2 else 'second'
            running=json.loads((folder/f'running-{form}.json').read_text(encoding='utf8'))
            view.web.page().runJavaScript('window.HsinPmxDebug.startRunningTrial('+json.dumps(running)+');')
            samples.clear()
        if not args.verify:QTimer.singleShot(800,lambda:window.grab().save(str(folder/'interactive-preview.png')))
        if args.verify and not busy:
            busy=True
            if not args.running:QTimer.singleShot(2400,capture)
    view.load_finished.connect(loaded)
    def capture():
        nonlocal index,busy
        label=choice.currentText();window.grab().save(str(folder/f'preview-{index}.png'))
        def record(value):
            nonlocal index,busy
            bones=json.loads(value);assert bones and all(all(__import__('math').isfinite(v) for v in b['position']+b['rotation']) for b in bones)
            results.append({'label':label,'texture_errors':view.model_info['texture_errors'],'runtime':view.model_info.get('runtime'),'bones':bones,'running_samples':list(samples)})
            index+=1;busy=False
            if index<len(labels):choice.setCurrentIndex(index)
            else:app.quit()
        view.web.page().runJavaScript('JSON.stringify(window.HsinPmxDebug.trialChest());',record)
    def sample():
        nonlocal sample_busy
        if not args.running or not ready_once or not view.model_loaded or sample_busy:return
        sample_busy=True
        def record(value):
            nonlocal sample_busy
            sample_busy=False
            if not value:return
            state=json.loads(value);samples.append(state)
            if not state['finite'] or (state['post_count'] and state['max_error']>1e-4):
                errors.append('物理后继承误差/非有限骨骼：'+str(state['max_error']));app.quit();return
            if args.verify and busy and state['elapsed']>=16: capture()
        view.web.page().runJavaScript('JSON.stringify(window.HsinPmxDebug.runningState());',record)
    sample_timer=QTimer(window);sample_timer.timeout.connect(sample);sample_timer.start(500)
    choice.setCurrentIndex(1 if not args.verify else 0)
    window.show()
    if args.running and not args.verify:sample_timer.stop()
    if args.verify:QTimer.singleShot(360000,app.quit)
    app.aboutToQuit.connect(view.cleanup)
    app.exec()
    if args.verify:
        success=len(results)==4 and not errors and all(r['texture_errors']==0 for r in results)
        (folder/('running-report.json' if args.running else 'preview-report.json')).write_text(json.dumps({'success':success,'errors':errors,'results':results},ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'success':success,'models':len(results),'errors':errors},ensure_ascii=False))
        return 0 if success else 1
    return 0

if __name__=='__main__':raise SystemExit(main())
