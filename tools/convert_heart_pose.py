"""提取参考 VPD 的上半身旋转，供直接 PMX 管线校准；不包含 GLB 绑定常量。"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def convert(source: Path, output: Path):
    raw = source.read_bytes()
    poses = []
    for name, body in re.findall(r"Bone\d+\{([^\r\n]+)\s*([^}]+)\}", raw.decode("cp932")):
        if name not in ("首", "頭") and not re.fullmatch(r"[左右](腕|腕捩|ひじ|手捩|手首|(親|人|中|薬|小)指[０１２３])", name):
            continue
        values = re.findall(r"([-\d.,]+);", body)
        rotation = list(map(float, values[1].split(",")))
        if len(rotation) != 4:
            raise ValueError(f"VPD 旋转无效：{name}")
        poses.append({"name": name, "rotation": rotation})
    if len(poses) != 42:
        raise ValueError(f"需要 42 根头颈/手臂/手指骨骼，实际 {len(poses)}")
    output.write_text(
        "// 由 tools/convert_heart_pose.py 从 heartmark001.vpd 提取；仅旋转，未转换坐标。\n"
        f"// VPD SHA256: {hashlib.sha256(raw).hexdigest()}\n"
        "export const HEART_POSE = " + json.dumps(poses, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf8",
    )
    print(f"已提取 {len(poses)} 根骨骼：{output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert(args.source, args.output)
