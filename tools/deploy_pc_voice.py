"""将最小桥接代码部署到 PC 的独立运行目录；不覆盖工作区或已有服务。"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
from pathlib import Path
import subprocess
import zipfile


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_remote(destination: str, identity: Path, script: str) -> str:
    script = "$ProgressPreference='SilentlyContinue'; " + script
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return subprocess.check_output(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-i", str(identity),
                                    destination, "powershell -NoProfile -EncodedCommand " + encoded], text=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.50.230")
    parser.add_argument("--user", default="lianj")
    parser.add_argument("--identity", type=Path, default=Path.home() / ".ssh/id_ed25519")
    parser.add_argument("--pc-root", default="D:/Workspace/Code Hsin")
    parser.add_argument("--gpu-uuid", required=True)
    parser.add_argument("--aemeath-profiles", help="PC 上已验证的爱弥斯音色 JSON 路径")
    parser.add_argument("--token-file", help="PC 上的私有访问令牌文件；公网入口必须配置")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    release_name = datetime.now().strftime("%Y%m%d-%H%M%S")
    remote_root = options.pc_root + "/.runtime/pc-voice-bridge/" + release_name
    destination = options.user + "@" + options.host
    # 已占用端口意味着可能存在用户服务；拒绝替换，交给显式的运维步骤。
    preparation = "$ErrorActionPreference='Stop'; " + \
        f"$voiceGpu=nvidia-smi --query-gpu=name,uuid --format=csv,noheader | Where-Object {{ $_.Contains({powershell_quote(options.gpu_uuid)}) }}; " + \
        "if (-not $voiceGpu -or $voiceGpu -match '5060') { throw 'GPU unavailable or prohibited RTX 5060' }; " + \
        "if (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 19881,19882 }) { throw 'Voice port already in use' }; " + \
        f"New-Item -ItemType Directory -Force -Path {powershell_quote(remote_root)} | Out-Null"
    run_remote(destination, options.identity, preparation)
    asr_python = options.pc_root + "/.runtime/local-model-tests/venv-asr/Scripts/python.exe"
    settings = {"runtime": remote_root + "/runtime", "gpu_uuid": options.gpu_uuid,
                "asr_python": asr_python, "asr_model": options.pc_root + "/.runtime/local-model-tests/models/qwen3-asr",
                "voice_profiles": options.pc_root + "/voice/profiles.json", "tts_port": 19882,
                "hermes": {"home": "C:/Users/" + options.user + "/AppData/Local/hermes", "profile": "default", "url": ""}}
    if options.token_file:
        settings["token_file"] = options.token_file
    if options.aemeath_profiles:
        settings["voice_catalog"] = {"aemeath": options.aemeath_profiles}
    local_root = root / ".runtime/pc-voice-deploy" / release_name
    local_root.mkdir(parents=True)
    archive_path = local_root / "code.zip"
    files = ["src/__init__.py", "src/core/__init__.py", "src/core/app_config.py", "src/core/stt_hotwords.py",
             "src/core/local_synthesizer.py", "src/core/voice_catalog.py", "src/core/preset_voice.py", "src/core/model_process.py",
             "src/core/qwen_worker.py", "src/core/pc_hermes.py", "src/core/hermes_bridge.py",
             "src/core/chat_preferences.py", "tools/hsin_voice_server.py", "tools/hsin_pc_voice_server.py"]
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename in files:
            archive.write(root / filename, "code/" + filename)
        archive.writestr("bridge.json", json.dumps(settings))
        launcher = "\n".join(["import pathlib,runpy,sys", "root=pathlib.Path(__file__).resolve().parent",
                              "sys.stdout=(root/'stdout.log').open('a',encoding='utf8',buffering=1)",
                              "sys.stderr=(root/'stderr.log').open('a',encoding='utf8',buffering=1)",
                              "sys.argv=[str(root/'code/tools/hsin_pc_voice_server.py'),'--config',str(root/'bridge.json')]",
                              "runpy.run_path(sys.argv[0],run_name='__main__')"])
        archive.writestr("run_bridge.py", launcher)
    subprocess.run(["scp", "-i", str(options.identity), str(archive_path), destination + ":" + remote_root + "/code.zip"], check=True)
    # WMI 创建进程避免继承 SSH 会话的 Windows Job；SSH 退出后服务仍可运行。
    command = f'"{asr_python}" -u "{remote_root}/run_bridge.py"'
    deployment = "$ErrorActionPreference='Stop'; " + \
        f"Expand-Archive -LiteralPath {powershell_quote(remote_root + '/code.zip')} -DestinationPath {powershell_quote(remote_root)}; " + \
        "$voiceLaunch=Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{" + \
        f"CommandLine={powershell_quote(command)};CurrentDirectory={powershell_quote(remote_root + '/code')}}}; " + \
        "if ($voiceLaunch.ReturnValue -ne 0) { throw 'Voice launch failed' }; $voiceLaunch.ProcessId"
    process_id = run_remote(destination, options.identity, deployment).strip()
    receipt = {"host": options.host, "remote_root": remote_root, "pid": process_id,
               "gpu_uuid": options.gpu_uuid, "ports": [19881, 19882]}
    (root / ".runtime/pc-voice-deployment.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
