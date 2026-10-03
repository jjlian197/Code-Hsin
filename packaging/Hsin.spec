from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
datas = [(str(root / 'src/assets'), 'src/assets'),
         (str(root / 'voice/presets'), 'voice/presets'),
         (str(root / 'voice/recordings'), 'voice/recordings'),
         (str(root / 'voice/samples'), 'voice/samples'),
         (str(root / 'tools/hsin_voice_server.py'), 'tools')]
for package in ('PyQt6', 'PyQt6-WebEngine', 'PyQt6-Qt6', 'PyQt6-WebEngine-Qt6', 'PyQt6-sip',
                'edge-tts', 'websockets', 'aiohttp', 'requests', 'PyYAML', 'loguru', 'webrtcvad-wheels'):
    datas += copy_metadata(package)
hiddenimports = ['webrtcvad', '_webrtcvad', 'edge_tts']
a = Analysis([str(root / 'packaging/entry.py')], pathex=[str(root)],
             binaries=[],
             datas=datas, hiddenimports=hiddenimports,
             hookspath=[str(root / 'packaging/hooks')],
             excludes=['torch', 'transformers', 'tensorflow', 'matplotlib', 'pandas', 'IPython', 'pytest', 'PyQt5', 'PySide6',
                       'scipy', 'sympy', 'sklearn', 'nltk', 'onnxruntime.tools', 'onnxruntime.quantization',
                       'torchvision', 'torchaudio', 'torchgen', 'torchtext', 'cv2', 'numba', 'llvmlite',
                       'librosa', 'soundfile', 'skimage', 'keras', 'fastai', 'gradio', 'streamlit',
                       'notebook', 'jupyter', 'tkinter', 'faster_whisper', 'ctranslate2', 'tokenizers',
                       'onnxruntime', 'av', 'numpy'],
             noarchive=False)
# Qt 6 使用 Windows 系统 ICU。环境 PATH 中的 Poppler ICU 同名但导出不兼容，不能打入包中。
a.binaries = [item for item in a.binaries
              if Path(item[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll', 'cudnn64_9.dll'}
              and Path(item[0]).parts[0].lower() != 'torch']
a.datas = [item for item in a.datas if Path(item[0]).parts[0].lower() != 'torch']
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Hsin',
          console=False, debug=False, upx=False, icon=str(root / 'src/assets/icons/hsin.png'))
coll = COLLECT(exe, a.binaries, a.datas, name='Hsin', upx=False)
