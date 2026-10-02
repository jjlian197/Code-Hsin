"""复用参考项目已有连接凭据，只写本项目未跟踪的本机配置。"""
import ast
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path("D:/Workspace/aemeath-spirit")


def main():
    path = ROOT / "config.local.yaml"
    local = yaml.safe_load(path.read_text(encoding="utf8")) if path.is_file() else {}
    local = local or {}
    chat = local.setdefault("chat", {})
    direct = chat.setdefault("deepseek", {})
    for file in (REFERENCE / "config.yaml", REFERENCE / "config.local.yaml"):
        if file.is_file():
            data = yaml.safe_load(file.read_text(encoding="utf8")) or {}
            existing = (data.get("voice_chat") or {}).get("deepseek") or {}
            if not direct.get("api_key") and existing.get("api_key"):
                direct["api_key"] = existing["api_key"]
            if existing.get("model"):
                direct.setdefault("model", existing["model"])
    claw = chat.setdefault("openclaw", {})
    if not claw.get("token"):
        file = REFERENCE / "src/core/openclaw_bridge.py"
        if file.is_file():
            tree = ast.parse(file.read_text(encoding="utf8"))
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_GATEWAY_TOKEN" for t in node.targets):
                    claw["token"] = ast.literal_eval(node.value)
    temp = path.with_suffix(".tmp")
    temp.write_text(yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf8")
    temp.replace(path)
    report = {"deepseek_key_available": bool(direct.get("api_key")), "openclaw_token_available": bool(claw.get("token")),
              "hermes": "existing_desktop_default_profile_Hsin", "credentials_output": "not_printed"}
    (ROOT / ".runtime/chat-connections.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
