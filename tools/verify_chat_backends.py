"""用简短对话检查实际后端；结果保存在项目内，绝不输出凭据。"""
import argparse
import asyncio
import json
from pathlib import Path
from src.core.app_config import load_config
from src.core.chat_backends import make_backend

ROOT=Path(__file__).resolve().parents[1]


async def verify(providers):
    config=load_config()["chat"]
    path=ROOT/".runtime/chat-backend-validation.json"
    report=json.loads(path.read_text(encoding="utf8")) if path.is_file() else {}
    for provider in providers:
        backend=make_backend(provider,config[provider])
        rows=[]
        try:
            for language,text in (("zh","这是桌面精灵连接测试。请用心的身份，向御者说一句简短问候。不要使用工具。"),
                                  ("ja","前の挨拶で私を何と呼んだ？日本語の一文だけで答えて。ツールは使わないで。")):
                chunks=[]
                async def delta(t): chunks.append(t)
                reply=await backend.chat(text,language,delta)
                assert reply.strip()
                rows.append({"language":language,"reply":reply,"stream_chunks":len(chunks)})
                print(f"PASS {provider} {language} reply",flush=True)
            report[provider]={"success":True,"turns":rows,"endpoint":getattr(backend,"endpoint",None)}
        except Exception as exc:
            report[provider]={"success":False,"turns":rows,"error_type":type(exc).__name__}
            print(f"FAIL {provider}: {type(exc).__name__}",flush=True)
        finally:
            if hasattr(backend,"close"):
                await backend.close()
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    return 0 if all(report[p]["success"] for p in providers) else 1


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("providers",nargs="+",choices=("hermes","deepseek","openclaw"))
    args=parser.parse_args()
    raise SystemExit(asyncio.run(verify(args.providers)))
