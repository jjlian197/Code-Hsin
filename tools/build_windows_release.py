"""构建 Windows 便携包：显式资源清单，不打包模型、密钥或运行记录。"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', default='1.1.0')
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    if not all(part.isdigit() for part in args.version.split('.')) or len(args.version.split('.')) != 3:
        raise ValueError('版本号需要 x.y.z')
    for path in ('voice/presets/manifest.json', 'voice/recordings/manifest.json'):
        if not (ROOT / path).is_file():
            raise ValueError('请先运行 python -m tools.prepare_release_voice')
    if not args.skip_build:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(ROOT / 'dist'),
                        '--workpath', str(ROOT / 'build'), str(ROOT / 'packaging/Hsin.spec')], cwd=ROOT, check=True)
    folder = ROOT / 'dist/Hsin'
    if not (folder / 'Hsin.exe').is_file():
        raise FileNotFoundError('缺少构建的 EXE')
    shutil.copyfile(ROOT / 'packaging/config.yaml', folder / 'config.yaml')
    shutil.copyfile(ROOT / 'docs/WINDOWS_EXE.md', folder / '使用说明.md')
    shutil.copyfile(ROOT / 'docs/RELEASE_NOTES.md', folder / '发布说明.md')
    shutil.copyfile(ROOT / 'docs/DEPENDENCY_LICENSES.md', folder / '第三方说明.md')
    shutil.copyfile(ROOT / 'LICENSE', folder / 'LICENSE')
    shutil.copyfile(ROOT / 'docs/GPT_SOVITS_SETUP.md', folder / 'GPT-SoVITS部署说明.md')
    shutil.copytree(ROOT / 'voice/config-templates', folder / 'voice/config-templates', dirs_exist_ok=True)
    forbidden = {'config.local.yaml', 'profiles.json', 'model.bin', 'pytorch_model.bin'}
    for file in folder.rglob('*'):
        if file.is_file() and (file.name in forbidden or file.suffix.lower() in {'.pmx', '.ckpt', '.pth', '.safetensors', '.fbx'}
                              or '.runtime' in file.relative_to(folder).parts):
            raise ValueError(f'发行包包含应排除的资源：{file.relative_to(folder)}')
    releases = ROOT / 'release'
    releases.mkdir(exist_ok=True)
    archive = releases / f'Code-Hsin-v{args.version}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(folder.rglob('*')):
            if file.is_file():
                bundle.write(file, Path('Hsin') / file.relative_to(folder))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='ascii')
    print(f'Release: {archive.name}; {archive.stat().st_size / 1024**2:.1f} MiB; SHA256 {checksum}', flush=True)
    for name, source in (('desktop-spirit-engineering', ROOT / 'skills/desktop-spirit-engineering'),
                         ('Hsin-GPTSoVITS-configs', ROOT / 'voice/config-templates')):
        extra = releases / f'{name}-v{args.version}.zip'
        with zipfile.ZipFile(extra, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for file in sorted(source.rglob('*')):
                if file.is_file():
                    bundle.write(file, Path(source.name) / file.relative_to(source))
            if name == 'Hsin-GPTSoVITS-configs':
                bundle.write(ROOT / 'docs/GPT_SOVITS_SETUP.md', 'GPT_SOVITS_SETUP.md')
        checksum = hashlib.sha256(extra.read_bytes()).hexdigest()
        extra.with_suffix('.zip.sha256').write_text(f'{checksum}  {extra.name}\n', encoding='ascii')
        print(f'Release: {extra.name}', flush=True)


if __name__ == '__main__':
    main()
