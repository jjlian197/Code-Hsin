"""汇总共同负载采样并导出资源曲线；不运行模型。"""
import argparse
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in (args.folder / 'samples.jsonl').read_text(encoding='utf-8').splitlines()]
    report = json.loads((args.folder / 'report.json').read_text(encoding='utf-8'))
    def gpu(row):
        return next(value['used_mib'] for value in row['gpus'] if '4080 SUPER' in value['name'])
    baseline = statistics.median(gpu(row) for row in rows if row['phase'] == 'baseline')
    active = [row for row in rows if row['phase'].startswith(('turn-', 'warmup-')) and row['seconds'] > 100]
    # 早期记录在清理刚开始时仍标为idle；要求ASR/TTS仍驻留，排除退出样本。
    idle = [row for row in rows if row['phase'].startswith('idle-')
            and any(p['group'] == 'asr' and p['rss_mib'] > 1000 for p in row['processes'])
            and any(p['group'] == 'gpt_sovits' and p['rss_mib'] > 1000 for p in row['processes'])]
    def stats(values):
        return {name: round(value, 2) for name, value in {'min': min(values), 'median': statistics.median(values), 'max': max(values)}.items()}
    def window(values):
        return {'count': len(values), 'whole_gpu_mib': stats([gpu(row) for row in values]),
                'rss_mib': stats([row['owned_rss_mib'] for row in values]),
                'private_ram_mib': stats([row['owned_private_working_set_mib'] for row in values])}
    summary = {'success': report['success'], 'turns': len(report['turns']), 'duration_seconds': report['duration_seconds'],
               'renderer': report.get('renderer'), 'baseline_gpu_mib': baseline, 'active': window(active),
               'estimated_net_gpu_peak_mib': max(gpu(row) for row in rows) - baseline,
               'owned_rss_peak_mib': max(row['owned_rss_mib'] for row in rows),
               'owned_private_ram_peak_mib': max(row['owned_private_working_set_mib'] for row in rows),
               'early_active': window(active[:30]), 'late_active': window(active[-30:]),
               'groups': {}, 'gpu_process_counter_warning': 'PMX DedicatedUsage counter is inconsistent; do not sum process DedicatedUsage as physical VRAM.'}
    for group in ('pmx_app', 'asr', 'ollama', 'gpt_sovits'):
        summary['groups'][group] = {
            'rss_mib': stats([sum(proc['rss_mib'] for proc in row['processes'] if proc['group'] == group) for row in active]),
            'private_ram_mib': stats([sum(proc['private_working_set_mib'] for proc in row['processes'] if proc['group'] == group) for row in active])}
    if idle:
        summary['idle_first_30_seconds'] = window([row for row in idle if row['seconds'] < idle[0]['seconds'] + 30])
        summary['idle_last_15_seconds'] = window([row for row in idle if row['seconds'] > idle[-1]['seconds'] - 15])
        unloaded = [row for row in idle if not any(proc['name'] == 'llama-server.exe' for proc in row['processes'])]
        if unloaded:
            summary['idle_after_4b_release'] = window(unloaded)
    (args.folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'Microsoft YaHei'
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    x = [row['seconds'] / 60 for row in rows]
    axes[0].plot(x, [gpu(row) / 1024 for row in rows], label='4080S整卡实际显存')
    axes[0].axhline(baseline / 1024, linestyle='--', color='gray', label='测试前原有程序基线')
    axes[0].set_ylabel('显存 GiB')
    axes[1].plot(x, [row['owned_rss_mib'] / 1024 for row in rows], label='本次进程驻留内存（含共享页）')
    axes[1].plot(x, [row['owned_private_working_set_mib'] / 1024 for row in rows], label='本次进程私有物理内存')
    axes[1].set_ylabel('内存 GiB')
    axes[1].set_xlabel('采样开始后的分钟数')
    for ax in axes:
        if idle:
            ax.axvspan(idle[0]['seconds'] / 60, idle[-1]['seconds'] / 60, color='green', alpha=.08, label='5分钟闲置观察')
        ax.legend(loc='best', fontsize=9)
        ax.grid(alpha=.2)
    fig.suptitle('PMX + Qwen ASR + 4B + GPT-SoVITS：同卡共同负载')
    fig.tight_layout()
    fig.savefig(args.folder / 'resources.png', dpi=160)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
