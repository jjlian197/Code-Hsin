"""解析 CMU ASF/AMC：按骨骼轴、DOF 和层级还原世界空间；离线生成可检查的源动作。"""
import argparse
import hashlib
import json
from urllib.request import urlopen
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def read_asf(path):
    sections, current = {}, None
    for raw in Path(path).read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(":"):
            current = line[1:].split()[0]
            sections[current] = []
        else:
            sections[current].append(line)
    units = dict(line.split(maxsplit=1) for line in sections["units"])
    if units["angle"] != "deg":
        raise ValueError("需要角度制 ASF")
    root = dict(line.split(maxsplit=1) for line in sections["root"])
    if root["order"].split() != ["TX", "TY", "TZ", "RX", "RY", "RZ"]:
        raise ValueError("不支持的根通道顺序")
    bones, item = {}, None
    for line in sections["bonedata"]:
        words = line.split()
        if words[0] == "begin":
            item = {"dof": []}
        elif words[0] == "end":
            bones[item["name"]] = item
        elif words[0] == "name":
            item["name"] = words[1]
        elif words[0] in {"direction", "axis"}:
            item[words[0]] = [float(x) for x in words[1:4]]
            if words[0] == "axis" and words[4] != "XYZ":
                raise ValueError("不支持的 ASF 轴顺序")
        elif words[0] == "length":
            item["length"] = float(words[1])
        elif words[0] == "dof":
            item["dof"] = words[1:]
    parents = {}
    for line in sections["hierarchy"]:
        words = line.split()
        if words[0] not in {"begin", "end"}:
            parents.update({child: words[0] for child in words[1:]})
    if set(parents) != set(bones):
        raise ValueError("ASF 层级不完整")
    return {"bones": bones, "parents": parents, "root": root, "units": units}


def read_amc(path, skeleton):
    frames, current, number = [], None, 0
    for raw in Path(path).read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line or line[0] in "#:" :
            continue
        if line.isdecimal():
            if int(line) != number + 1:
                raise ValueError("AMC 帧号不连续")
            number += 1
            current = {}
            frames.append(current)
        else:
            words = line.split()
            name = words[0]
            values = [float(x) for x in words[1:]]
            dof = 6 if name == "root" else len(skeleton["bones"][name]["dof"])
            if current is None or len(values) != dof or not np.isfinite(values).all():
                raise ValueError("AMC 通道无效")
            current[name] = values
    required = {"root"} | {name for name, bone in skeleton["bones"].items() if bone["dof"]}
    if not frames or any(set(frame) != required for frame in frames):
        raise ValueError("AMC 缺少完整通道")
    return frames


def forward_kinematics(skeleton, frames):
    bones, parents = skeleton["bones"], skeleton["parents"]
    order = ["root"]
    while len(order) <= len(bones):
        ready = [name for name in bones if name not in order and parents[name] in order]
        if not ready:
            raise ValueError("ASF 层级存在循环")
        order.extend(ready)
    positions = {name: [] for name in order}
    rotations = {name: [] for name in order}
    # 保留 ASF 原始长度单位；重定向按骨长比例处理，不猜测真人身高。
    scale = 1.0
    axes = {name: Rotation.from_euler("xyz", bone["axis"], degrees=True).as_matrix() for name, bone in bones.items()}
    for frame in frames:
        matrices = {"root": Rotation.from_euler("xyz", frame["root"][3:], degrees=True).as_matrix()}
        points = {"root": np.array(frame["root"][:3]) * scale}
        for name in order[1:]:
            bone, parent = bones[name], parents[name]
            angles = dict(zip(bone["dof"], frame.get(name, [])))
            motion = Rotation.from_euler("xyz", [angles.get("r" + axis, 0) for axis in "xyz"], degrees=True).as_matrix()
            matrices[name] = matrices[parent] @ axes[name] @ motion @ axes[name].T
            points[name] = points[parent] + matrices[name] @ (np.array(bone["direction"]) * bone["length"] * scale)
        for name in order:
            positions[name].append(points[name].tolist())
            rotations[name].append(Rotation.from_matrix(matrices[name]).as_quat().tolist())
    return {"fps": 120, "frames": len(frames), "parents": parents, "positions": positions, "rotations": rotations,
            "units": "asf_native", "source_units": skeleton["units"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path("motions/cmu"))
    parser.add_argument("--output", type=Path, default=Path(".runtime/cmu"))
    args = parser.parse_args()
    for subject, motion in (("113", "113_08"), ("140", "140_03")):
        for filename in (f"{subject}.asf", f"{motion}.amc"):
            target = args.directory / filename
            if not target.is_file():
                args.directory.mkdir(parents=True, exist_ok=True)
                url = f"https://mocap.cs.cmu.edu/subjects/{subject}/{filename}"
                with urlopen(url, timeout=45) as response:
                    contents = response.read()
                if not contents or contents.lstrip().startswith(b"<"):
                    raise ValueError("CMU 返回了无效的动作文件")
                target.write_bytes(contents)
    args.output.mkdir(parents=True, exist_ok=True)
    for subject, motion in (("113", "113_08"), ("140", "140_03")):
        asf, amc = args.directory / f"{subject}.asf", args.directory / f"{motion}.amc"
        skeleton = read_asf(asf)
        result = forward_kinematics(skeleton, read_amc(amc, skeleton))
        result["source"] = {"asf": f"https://mocap.cs.cmu.edu/subjects/{subject}/{subject}.asf",
            "amc": f"https://mocap.cs.cmu.edu/subjects/{subject}/{motion}.amc",
            "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (asf, amc)}}
        (args.output / f"{motion}.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf8")
        root, head = np.array(result["positions"]["root"]), np.array(result["positions"]["head"])
        print(motion, result["frames"], "seconds", result["frames"] / 120, "root_y", root[:, 1].min(), root[:, 1].max(), "head_y", head[:, 1].min(), head[:, 1].max())


if __name__ == "__main__":
    main()
