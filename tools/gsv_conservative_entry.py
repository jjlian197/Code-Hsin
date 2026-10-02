"""在进程内限制资源后运行安装版 S1；不修改安装目录和模型架构。"""
import os
from functools import wraps
from pathlib import Path
import runpy
import sys


def main():
    root = Path.cwd()
    script = root / "GPT_SoVITS/s1_train.py"
    if not script.is_file():
        raise ValueError("必须从 GPT-SoVITS 安装目录启动")
    os.environ.update(OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    # 动态长度语音会产生不同大小的张量，合并可扩展段以减少显存碎片。
    os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
    sys.path[:0] = [str(root), str(root / "GPT_SoVITS")]
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    if torch.cuda.is_available():
        # 超出上限时让训练进程报错退出，留出桌面与其他应用的显存。
        torch.cuda.set_per_process_memory_fraction(0.75, 0)
        from AR.modules.optim import ScaledAdam
        original_step = ScaledAdam.step

        @wraps(original_step)
        def step_with_released_pool(self, *args, **kwargs):
            # 反向传播结束后释放空闲缓存，给优化器的临时张量留下连续空间。
            # 只清理未被张量占用的显存，不改变参数、梯度或优化器状态。
            torch.cuda.empty_cache()
            return original_step(self, *args, **kwargs)

        ScaledAdam.step = step_with_released_pool
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
