"""心专用本地推理服务；语言权重切换与合成在同一把锁内完成。"""
import argparse
import io
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--port", type=int, default=19880)
    args = parser.parse_args()
    # 中日切换和不同句长共用显存池，避免保留碎片挤占资源上限。
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    profiles_path = Path(args.profiles).resolve()
    profiles = json.loads(profiles_path.read_text(encoding="utf8"))
    runtime = Path(args.runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    root = Path(profiles["installation"]["gptsovits_root"])
    os.chdir(root)
    sys.path[:0] = [str(root), str(root / "GPT_SoVITS")]
    lock = threading.Lock()
    engine = None
    active = None
    active_identity = None
    torch_initialized = False

    def synthesize(request):
        nonlocal engine, active, active_identity, torch_initialized
        language, text = request.get("language"), request.get("text")
        speed = request.get("speed", 1.0)
        if language not in profiles["profiles"] or not isinstance(text, str) or not 1 <= len(text.strip()) <= 500:
            raise ValueError("需要 zh/ja 语言和 1–500 字符的文本")
        if type(speed) not in (int, float) or not 0.5 <= speed <= 2:
            raise ValueError("语速需要在 0.5–2 之间")
        profile = profiles["profiles"][language]
        with lock:
            if not torch_initialized:
                import torch
                torch.set_num_threads(2)
                torch.set_num_interop_threads(2)
                if torch.cuda.is_available():
                    torch.cuda.set_per_process_memory_fraction(0.75, 0)
                torch_initialized = True
            identity = tuple((str(Path(profile[key]).resolve()), Path(profile[key]).stat().st_size,
                              Path(profile[key]).stat().st_mtime_ns)
                             for key in ("gpt_weights", "sovits_weights", "reference_audio"))
            # 延迟载入，使桌面窗口不必等待 GPU 模型启动。
            from GPT_SoVITS.TTS_infer_pack.TTS import TTS
            import numpy as np
            import soundfile as sf
            if engine is None:
                import yaml
                prep = profiles["installation"]
                config = {"custom": {"version": "v2ProPlus", "device": "cuda", "is_half": True,
                          "t2s_weights_path": profile["gpt_weights"], "vits_weights_path": profile["sovits_weights"],
                          "bert_base_path": prep["bert_pretrained_dir"],
                          "cnhuhbert_base_path": prep["cnhubert_base_dir"]}}
                config_path = runtime / "tts_infer.yaml"
                config_path.write_text(yaml.safe_dump(config), encoding="utf8")
                engine = TTS(str(config_path))
                active = language
                active_identity = identity
            elif active != language or active_identity != identity:
                active = None  # 任一权重加载失败后，下一次请求必须重载两套。
                engine.init_t2s_weights(profile["gpt_weights"])
                engine.init_vits_weights(profile["sovits_weights"])
                engine.prompt_cache = {"ref_audio_path": None, "prompt_semantic": None, "refer_spec": [],
                    "prompt_text": None, "prompt_lang": None, "phones": None, "bert_features": None,
                    "norm_text": None, "aux_ref_audio_paths": []}
                active = language
                active_identity = identity
            params = {"text": text.strip(), "text_lang": language, "prompt_lang": language,
                      "prompt_text": profile["prompt_text"], "ref_audio_path": profile["reference_audio"],
                      "text_split_method": "cut5", "batch_size": 1, "top_k": 5, "top_p": 1,
                      "temperature": 1, "speed_factor": speed, "seed": 1234,
                      "parallel_infer": False, "repetition_penalty": 1.35, "streaming_mode": False}
            chunks = list(engine.run(params))
            if not chunks or any(rate != chunks[0][0] for rate, _ in chunks):
                raise RuntimeError("合成未产生一致的音频")
            data = np.concatenate([audio for _, audio in chunks])
            if not data.size or not np.any(data):
                raise RuntimeError("合成结果为空或完全静音")
            stream = io.BytesIO()
            sf.write(stream, data, chunks[0][0], format="WAV", subtype="PCM_16")
            return stream.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, payload, content_type="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.send(200, {"service": "hsin-gptsovits", "profile_id": profiles["profile_id"],
                                "languages": list(profiles["profiles"]), "active_language": active})
            else:
                self.send(404, {"error": "unknown endpoint"})

        def do_POST(self):
            if self.path != "/tts":
                return self.send(404, {"error": "unknown endpoint"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("请求长度无效")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("请求需要 JSON 对象")
                audio = synthesize(payload)
                self.send(200, audio, "audio/wav")
            except ValueError as exc:
                self.send(400, {"error": str(exc)})
            except Exception as exc:
                traceback.print_exc()
                self.send(500, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
