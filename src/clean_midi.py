"""Post-process MIDI to remove noise: short notes, low velocity, isolated notes,
music-theory checks, pitch distribution filtering, rhythm filtering,
and energy-weighted filtering."""
import sys
import numpy as np
import pretty_midi
from collections import Counter


def clean_midi(input_path, output_path,
               min_duration=0.05,      # 最短音符时长(秒)
               min_velocity=20,         # 最低力度
               min_gap=0.02,           # 同音高最短间隔
               merge_gap=0.08,         # 合并间隔内的同音高音符
               isolated_window=0.1,    # 孤立音符检测窗口
               max_simultaneous=8,     # 同时按键最大数量
               max_pitch_jump=24,      # 最大音高跳跃(半音, 2个八度=24)
               rare_pitch_threshold=0.001,  # 稀有音高阈值(占总音符数比例)
               rapid_repeat_ms=50,     # 快速重复检测窗口(毫秒)
               rapid_repeat_count=3,   # 快速重复次数阈值
               weak_velocity_range=(20, 40),  # 弱音符力度范围
               strong_velocity=60,     # 强音符力度阈值
               energy_window=0.1):     # 能量检测窗口(秒)
    midi = pretty_midi.PrettyMIDI(input_path)
    total_notes_before = sum(len(inst.notes) for inst in midi.instruments)

    for inst in midi.instruments:
        notes = sorted(inst.notes, key=lambda n: (n.pitch, n.start))
        cleaned = []

        # Group by pitch
        pitch_notes = {}
        for n in notes:
            pitch_notes.setdefault(n.pitch, []).append(n)

        # --- Step 1: Merge close notes on same pitch (merge_gap=0.08, 取最大力度) ---
        for pitch, pnotes in pitch_notes.items():
            merged = [pnotes[0]]
            for n in pnotes[1:]:
                prev = merged[-1]
                if n.start - prev.end < merge_gap:
                    prev.end = max(prev.end, n.end)
                    prev.velocity = max(prev.velocity, n.velocity)
                else:
                    merged.append(n)

            # --- Step 2: Filter by duration and velocity ---
            for n in merged:
                duration = n.end - n.start
                if duration < min_duration:
                    continue
                if n.velocity < min_velocity:
                    continue
                cleaned.append(n)

        # --- Step 3: Rapid repeat filtering (同一音高在50ms内重复>3次, 保留第一次) ---
        if cleaned:
            pitch_notes_cleaned = {}
            for n in cleaned:
                pitch_notes_cleaned.setdefault(n.pitch, []).append(n)

            after_rapid = []
            for pitch, pnotes in pitch_notes_cleaned.items():
                pnotes_sorted = sorted(pnotes, key=lambda n: n.start)
                kept = [pnotes_sorted[0]]
                for n in pnotes_sorted[1:]:
                    # 统计在 rapid_repeat_ms 窗口内已有的音符数
                    window_s = n.start - rapid_repeat_ms / 1000.0
                    recent_count = sum(1 for k in kept
                                       if k.start >= window_s and k.pitch == pitch)
                    if recent_count < rapid_repeat_count:
                        kept.append(n)
                after_rapid.extend(kept)
            cleaned = after_rapid

        # --- Step 4: Pitch distribution filtering (低频+低力度移除) ---
        if cleaned:
            total_count = len(cleaned)
            pitch_counter = Counter(n.pitch for n in cleaned)
            rare_threshold_count = max(1, int(total_count * rare_pitch_threshold))
            avg_velocity = np.mean([n.velocity for n in cleaned]) if cleaned else 0

            after_pitch = []
            for n in cleaned:
                freq = pitch_counter[n.pitch]
                # 频率极低且力度低于平均值 -> 移除
                if freq < rare_threshold_count and n.velocity < avg_velocity:
                    continue
                after_pitch.append(n)
            cleaned = after_pitch

        # --- Step 5: Music theory checks ---
        if cleaned:
            # 5a: 检测极端音高跳跃 (1帧内音高变化超过2个八度)
            sorted_by_start = sorted(cleaned, key=lambda n: n.start)
            after_jump = []
            for i, n in enumerate(sorted_by_start):
                is_extreme_jump = False
                # 检查与前后音符的音高差
                for j in range(max(0, i - 3), min(len(sorted_by_start), i + 4)):
                    if i == j:
                        continue
                    other = sorted_by_start[j]
                    # 只检查时间上非常接近的音符(同帧, <0.01秒)
                    if abs(other.start - n.start) < 0.01:
                        if abs(other.pitch - n.pitch) > max_pitch_jump:
                            # 保留力度更高的那个
                            if other.velocity > n.velocity:
                                is_extreme_jump = True
                                break
                if not is_extreme_jump:
                    after_jump.append(n)
            cleaned = after_jump

            # 5b: 检测不可能的同时按键组合(超过8个键)
            # 按时间分组, 移除力度最低的多余音符
            if cleaned:
                sorted_by_start = sorted(cleaned, key=lambda n: n.start)
                # 将音符按时间窗口分组(10ms窗口)
                groups = []
                current_group = [sorted_by_start[0]]
                for n in sorted_by_start[1:]:
                    if n.start - current_group[0].start < 0.01:
                        current_group.append(n)
                    else:
                        groups.append(current_group)
                        current_group = [n]
                groups.append(current_group)

                after_simultaneous = []
                removed_pitches = set()
                for group in groups:
                    if len(group) > max_simultaneous:
                        # 按力度排序, 保留力度最高的 max_simultaneous 个
                        group_sorted = sorted(group, key=lambda n: n.velocity, reverse=True)
                        for n in group_sorted[max_simultaneous:]:
                            removed_pitches.add(id(n))
                        group = group_sorted[:max_simultaneous]
                    after_simultaneous.extend(group)
                cleaned = after_simultaneous

        # --- Step 6: Energy-weighted filtering (孤立弱音符移除) ---
        if cleaned:
            all_starts = np.array([n.start for n in cleaned])
            all_velocities = np.array([n.velocity for n in cleaned])

            after_energy = []
            for i, n in enumerate(cleaned):
                # 检查是否为弱音符
                if weak_velocity_range[0] <= n.velocity <= weak_velocity_range[1]:
                    # 检查周围是否有强音符
                    window_start = n.start - energy_window
                    window_end = n.start + energy_window
                    # 使用二分查找加速
                    left = np.searchsorted(all_starts, window_start)
                    right = np.searchsorted(all_starts, window_end)
                    has_strong = any(all_velocities[j] > strong_velocity
                                     for j in range(left, right)
                                     if j != i)
                    if not has_strong:
                        # 弱音符完全孤立, 移除
                        continue
                after_energy.append(n)
            cleaned = after_energy

        # --- Step 7: Remove isolated notes (no other notes within window) ---
        if cleaned:
            all_starts = sorted([n.start for n in cleaned])
            final = []
            for n in cleaned:
                nearby = sum(1 for s in all_starts
                             if abs(s - n.start) < isolated_window and s != n.start)
                if nearby >= 1:
                    final.append(n)
            inst.notes = final
        else:
            inst.notes = cleaned

    total_notes_after = sum(len(inst.notes) for inst in midi.instruments)
    midi.write(output_path)
    print(f"Cleaned: {total_notes_before} -> {total_notes_after} notes "
          f"(removed {total_notes_before - total_notes_after})")
    print(f"Saved to: {output_path}")


if __name__ == "__main__":
    input_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Administrator\Desktop\多多\测试\尸蜡_bytedance.mid"
    output_path = input_path.replace('.mid', '_clean.mid')
    clean_midi(input_path, output_path)
