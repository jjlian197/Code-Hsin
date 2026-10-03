from PyInstaller.utils.hooks import copy_metadata

# 本项目使用提供同名模块的 webrtcvad-wheels，原 hook 查错发行包名称。
datas = copy_metadata('webrtcvad-wheels')
hiddenimports = ['_webrtcvad']
