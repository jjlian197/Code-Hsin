"""直接核对冻结模块字节码，避免构建缓存使源码与发行EXE不一致。"""
import argparse
from pathlib import Path
from types import CodeType
from PyInstaller.archive.readers import CArchiveReader


def fingerprint(code):
    if isinstance(code, CodeType):
        return (code.co_code, tuple(fingerprint(value) for value in code.co_consts), code.co_names,
                code.co_varnames, code.co_freevars, code.co_cellvars, code.co_flags)
    if isinstance(code, tuple):
        return tuple(fingerprint(value) for value in code)
    return code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('exe')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    archive = CArchiveReader(args.exe).open_embedded_archive('PYZ.pyz')
    checked = 0
    for module in archive.toc:
        if module == 'src' or module.startswith('src.'):
            path = root / (module.replace('.', '/') + '.py')
            if not path.is_file():
                path = root / module.replace('.', '/') / '__init__.py'
            if not path.is_file():
                raise AssertionError('冻结模块缺少对应源码：' + module)
            source = compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
            assert fingerprint(source) == fingerprint(archive.extract(module)), '冻结模块与当前源码不一致：' + module
            checked += 1
    assert checked > 20
    print('Frozen source modules verified:', checked)


if __name__ == '__main__':
    main()
