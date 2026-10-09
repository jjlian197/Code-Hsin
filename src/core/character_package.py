"""读取只含数据的本地角色包；先验证资源，再允许切换角色。"""
import hashlib
import json
import math
from pathlib import Path

AEMEATH_HASHES = {
    "79b622d0a87ab61516d2c3008d241d9145daa905acbcbd29d070c68cc55fa437",
    "8b7294f38ace5dfae8ba65b400d4feb13897a1d15f828e285189fc56ef6f7854",
}
STANDING_MOTIONS = ["idle", "nod", "wave", "peace", "finger_heart", "crossed_arms", "treadmill_running"]


def load_character_package(file):
    file = Path(file).resolve()
    def read(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"角色包文件无法读取：{path.name}") from exc
    def resource(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("角色包资源路径无效")
        path = (file.parent / value).resolve()
        if not path.is_file():
            raise ValueError(f"角色包资源不存在：{path}")
        return path
    package = read(file)
    if not isinstance(package, dict) or package.get("format") != "hsin.character" or package.get("version") != 1:
        raise ValueError("角色包格式或版本不支持")
    if not isinstance(package.get("name"), str) or not package["name"].strip():
        raise ValueError("角色包需要名字")
    model = package.get("model", {})
    if not isinstance(model, dict):
        raise ValueError("角色包模型无效")
    path = resource(model.get("path"))
    if path.suffix.lower() != ".pmx":
        raise ValueError("角色包仅支持 PMX")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != model.get("sha256"):
        raise ValueError("角色包与当前 PMX 哈希不匹配")
    rig = read(resource(package.get("rig")))
    if not isinstance(rig, dict) or not isinstance(rig.get("model"), dict) or rig["model"].get("sha256") != digest or rig.get("schema") != "hsin.standard-rig" or rig.get("schemaVersion") != 1:
        raise ValueError("角色包骨架映射与模型不匹配")
    morphs = read(resource(package.get("morphs")))
    if not isinstance(morphs, dict) or morphs.get("version") != 1 or not isinstance(morphs.get("aliases"), dict) or not isinstance(morphs.get("expressions"), dict):
        raise ValueError("角色包表情映射无效")
    if morphs["expressions"].get("normal") != {}:
        raise ValueError("角色包平常表情必须为空")
    for target in morphs["aliases"].values():
        if target is not None and (not isinstance(target, str) or not target):
            raise ValueError("角色包表情别名无效")
    for weights in morphs["expressions"].values():
        if not isinstance(weights, dict) or any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 1 for v in weights.values()):
            raise ValueError("角色包表情权重无效")
    caps = package.get("capabilities", {})
    motions = caps.get("motions") if isinstance(caps, dict) else None
    allowed = STANDING_MOTIONS if digest in AEMEATH_HASHES else ["idle", "nod"]
    if (not isinstance(motions, list) or not motions or motions[0] != "idle"
            or any(not isinstance(name, str) or name not in allowed for name in motions)
            or len(set(motions)) != len(motions) or type(caps.get("physics")) is not bool):
        raise ValueError("角色包能力清单无效；复杂动作需要已校准的模型")
    # 兼容旧版爱弥斯角色包，无需用户重新导入；仍不开放侧躺。
    if digest in AEMEATH_HASHES and motions == ["idle", "nod"]:
        caps = {**caps, "motions": STANDING_MOTIONS.copy()}
    textures = model.get("textures", [])
    if not isinstance(textures, list):
        raise ValueError("角色包贴图列表无效")
    overrides = {}
    for item in textures:
        if not isinstance(item, dict) or not isinstance(item.get("source"), str) or not item["source"]:
            raise ValueError("角色包贴图引用无效")
        overrides[item["source"]] = str(resource(item.get("path")))
    return {"file": file, "name": package["name"], "model": path, "hash": digest,
            "rig": rig, "morphs": morphs, "capabilities": caps, "textures": overrides}
