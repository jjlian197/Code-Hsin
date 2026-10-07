"""把已验证的模型角色包和人设加入本机角色列表，保留当前角色及连接凭据。"""
import argparse
import json
import os
from pathlib import Path

from src.core.app_config import load_config
from src.core.character_package import load_character_package
from src.core.character_settings import profile_config, profile_from_config


def register_character(package_path: Path, persona_path: Path, data_root: Path | None) -> Path:
    if data_root is not None:
        os.environ['HSIN_DATA_DIR'] = str(data_root.resolve())
    config = load_config()
    package = load_character_package(package_path)
    persona = persona_path.read_text(encoding='utf8').strip()
    registry_path = Path(config['runtime']['directory']) / 'characters.json'
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding='utf8'))
        if registry.get('version') != 1 or not isinstance(registry.get('profiles'), list):
            raise ValueError('角色列表格式无效，保留原文件')
        for existing in registry['profiles']:
            profile_config(config, existing)
            if Path(existing['package']).resolve() == package_path.resolve():
                return registry_path  # 用户编辑过的人设不被重复安装覆盖。
    else:
        default_profile = profile_from_config(config)
        default_profile['id'] = 'hsin'
        registry = {'version': 1, 'active': 'hsin', 'profiles': [default_profile]}
    profile = profile_from_config(config, package['name'], str(package_path.resolve()), persona)
    # 当前 PC 桥接只配置了心的音色；先验证角色模型与人设，不冒充爱弥斯音色。
    profile['voice'].update(enabled=False, fallback=False)
    profile_config(config, profile)
    registry['profiles'].append(profile)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = registry_path.with_suffix('.pending')
    pending_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf8')
    pending_path.replace(registry_path)
    return registry_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--persona', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path)
    arguments = parser.parse_args()
    print(register_character(arguments.package, arguments.persona, arguments.data_dir))


if __name__ == '__main__':
    main()
