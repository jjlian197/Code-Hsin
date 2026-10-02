"""隔离本地识别原生依赖；父进程 JSON 行输入/输出，不引入 Qt。"""
import base64
import io
import json
import sys


def main():
    model = None
    model_path = None
    for line in sys.stdin:
        try:
            request = json.loads(line)
            path = request.get("model", "base")
            language = request.get("language", "zh")
            if language not in {"zh", "ja", "auto"}:
                raise ValueError("识别语言无效")
            audio = base64.b64decode(request["audio"], validate=True)
            if not 44 <= len(audio) <= 800100:
                raise ValueError("音频长度无效")
            if model is None or model_path != path:
                try:
                    from faster_whisper import WhisperModel
                    model = WhisperModel(path, device="cpu", compute_type="int8",
                        cpu_threads=4, num_workers=1, local_files_only=True)
                    model_path = path
                except Exception:
                    raise RuntimeError("本地 Whisper 模型不可用；请在麦克风设置中选择已下载的模型目录") from None
            segments, _ = model.transcribe(io.BytesIO(audio),
                language=None if language == "auto" else language, beam_size=3,
                condition_on_previous_text=False, vad_filter=True)
            response = {"text": "".join(segment.text for segment in segments).strip()[:4000]}
        except (RuntimeError, ValueError) as exc:
            response = {"error": str(exc)}
        except Exception:
            response = {"error": "本地 Whisper 识别失败"}
        print(json.dumps(response, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
