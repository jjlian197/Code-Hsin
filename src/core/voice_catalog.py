"""无 Qt 的音色选择契约，兼容 GPT-SoVITS 自带的 Python 3.9。"""
from __future__ import annotations
from typing import Any


def voice_profiles(configuration: dict[str, Any], voice_id: str = 'hsin') -> dict[str, Any]:
    """旧配置默认选择心；未安装的角色音色必须报错，避免串音色。"""
    if 'voices' in configuration:
        if voice_id not in configuration['voices']:
            raise ValueError('PC 音色未安装：' + voice_id)
        return configuration['voices'][voice_id]
    if voice_id != 'hsin':
        raise ValueError('PC 音色未安装：' + voice_id)
    return configuration['profiles']
