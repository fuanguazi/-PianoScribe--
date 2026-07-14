"""源分离 + 转录推理管道：Demucs分离 → ByteDance转录 → 合并MIDI"""
import os
import sys
import time
import argparse
import tempfile
import numpy as np
import librosa
import pretty_midi


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_PATH = os.path.join(_BASE_DIR, "checkpoints", "CRNN_note_F1=0.9677_pedal_F1=0.9186.pth")
SAMPLE_RATE = 16000  # piano_transcription_inference 的采样率
DEDUP_TOLERANCE_SEC = 0.03  # 去重容差 ±30ms


def separate_audio(audio_path, output_dir):
    """使用Demucs分离音频为人声和伴奏。

    Returns:
        (vocals_path, no_vocals_path) 或 (None, None) 表示失败
    """
    audio_basename = os.path.splitext(os.path.basename(audio_path))[0]
    # demucs默认输出结构: output_dir/htdemucs/audio_basename/vocals.wav
    htdemucs_dir = os.path.join(output_dir, "htdemucs", audio_basename)
    vocals_path = os.path.join(htdemucs_dir, "vocals.wav")
    no_vocals_path = os.path.join(htdemucs_dir, "no_vocals.wav")

    # 如果分离文件已存在，直接使用
    if os.path.isfile(vocals_path) and os.path.isfile(no_vocals_path):
        print(f"[分离] 已存在分离文件，跳过分离步骤:")
        print(f"  人声: {vocals_path}")
        print(f"  伴奏: {no_vocals_path}")
        return vocals_path, no_vocals_path

    print(f"[分离] 使用Demucs分离: {audio_path}")
    try:
        from demucs.separate import main as demucs_main
        # 构造demucs命令行参数
        old_argv = sys.argv
        try:
            sys.argv = [
                "demucs",
                "--two-stems=vocals",
                "-o", output_dir,
                audio_path,
            ]
            demucs_main()
        finally:
            sys.argv = old_argv

        if os.path.isfile(vocals_path) and os.path.isfile(no_vocals_path):
            print(f"[分离] 完成:")
            print(f"  人声: {vocals_path}")
            print(f"  伴奏: {no_vocals_path}")
            return vocals_path, no_vocals_path
        else:
            print(f"[分离] Demucs运行完成但未找到输出文件")
            return None, None
    except Exception as e:
        print(f"[分离] Demucs分离失败: {e}")
        return None, None


def transcribe_audio(audio_path, output_midi_path, device="cuda"):
    """使用ByteDance预训练模型转录音频，返回转录结果字典。"""
    from piano_transcription_inference import PianoTranscription, sample_rate

    print(f"[转录] 加载音频: {audio_path}")
    audio, sr = librosa.load(audio_path, sr=sample_rate, mono=True)
    print(f"[转录] 音频时长: {len(audio)/sample_rate:.1f}s")

    transcriptor = PianoTranscription(device=device, checkpoint_path=CHECKPOINT_PATH)
    transcribed_dict = transcriptor.transcribe(audio, output_midi_path)

    note_count = len(transcribed_dict.get("note", []))
    print(f"[转录] 完成，检测到 {note_count} 个音符")
    return transcribed_dict


def merge_midi(vocals_midi_path, no_vocals_midi_path, output_midi_path):
    """合并两个MIDI文件，去重（同音高±30ms保留力度更高的）。"""
    vocals_midi = pretty_midi.PrettyMIDI(vocals_midi_path)
    no_vocals_midi = pretty_midi.PrettyMIDI(no_vocals_midi_path)

    # 收集所有音符
    all_notes = []

    for instrument in vocals_midi.instruments:
        for note in instrument.notes:
            all_notes.append({
                "pitch": note.pitch,
                "start": note.start,
                "end": note.end,
                "velocity": note.velocity,
                "source": "vocals",
            })

    for instrument in no_vocals_midi.instruments:
        for note in instrument.notes:
            all_notes.append({
                "pitch": note.pitch,
                "start": note.start,
                "end": note.end,
                "velocity": note.velocity,
                "source": "no_vocals",
            })

    if not all_notes:
        print("[合并] 未检测到任何音符")
        # 创建空MIDI
        out_midi = pretty_midi.PrettyMIDI()
        out_midi.write(output_midi_path)
        return 0

    # 按开始时间排序
    all_notes.sort(key=lambda n: (n["start"], n["pitch"]))

    # 去重：同音高、同时间（±30ms）只保留力度更高的
    kept = []
    for note in all_notes:
        duplicate = False
        for existing in kept:
            if (existing["pitch"] == note["pitch"]
                    and abs(existing["start"] - note["start"]) <= DEDUP_TOLERANCE_SEC):
                # 同音高同时间，保留力度更高的
                if note["velocity"] > existing["velocity"]:
                    existing["start"] = note["start"]
                    existing["end"] = note["end"]
                    existing["velocity"] = note["velocity"]
                    existing["source"] = note["source"]
                duplicate = True
                break
        if not duplicate:
            kept.append(note)

    # 创建输出MIDI
    out_midi = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=0, name="Piano")
    for note in kept:
        midi_note = pretty_midi.Note(
            velocity=note["velocity"],
            pitch=note["pitch"],
            start=note["start"],
            end=note["end"],
        )
        instrument.notes.append(midi_note)
    out_midi.instruments.append(instrument)
    out_midi.write(output_midi_path)

    print(f"[合并] 合并完成: {len(all_notes)} → {len(kept)} 个音符（去重 {len(all_notes) - len(kept)} 个）")
    return len(kept)


def main():
    parser = argparse.ArgumentParser(description="源分离+转录推理管道")
    parser.add_argument("--audio", type=str, required=True, help="输入音频文件路径")
    parser.add_argument("--output", type=str, required=True, help="输出MIDI文件路径")
    parser.add_argument("--device", type=str, default="cuda", help="推理设备 (cuda/cpu)")
    parser.add_argument("--separate-output-dir", type=str, default=None,
                        help="Demucs分离输出目录（默认为音频同目录下的separated子目录）")
    args = parser.parse_args()

    total_start = time.time()

    # 确定分离输出目录
    if args.separate_output_dir:
        separate_dir = args.separate_output_dir
    else:
        audio_dir = os.path.dirname(os.path.abspath(args.audio))
        separate_dir = os.path.join(audio_dir, "separated")

    # 临时MIDI文件
    with tempfile.TemporaryDirectory(prefix="sat_") as temp_dir:
        vocals_midi = os.path.join(temp_dir, "vocals.mid")
        no_vocals_midi = os.path.join(temp_dir, "no_vocals.mid")

        # 步骤1：源分离
        step_start = time.time()
        vocals_path, no_vocals_path = separate_audio(args.audio, separate_dir)
        separate_time = time.time() - step_start

        if vocals_path and no_vocals_path:
            # 步骤2a：分别转录两个音轨
            print("\n=== 转录人声轨 ===")
            step_start = time.time()
            transcribe_audio(vocals_path, vocals_midi, args.device)
            vocals_time = time.time() - step_start

            print("\n=== 转录伴奏轨 ===")
            step_start = time.time()
            transcribe_audio(no_vocals_path, no_vocals_midi, args.device)
            no_vocals_time = time.time() - step_start

            # 步骤3：合并
            print("\n=== 合并MIDI ===")
            step_start = time.time()
            note_count = merge_midi(vocals_midi, no_vocals_midi, args.output)
            merge_time = time.time() - step_start
        else:
            # 降级：直接转录原始音频
            print("\n[降级] 分离失败，直接转录原始音频")
            step_start = time.time()
            transcribe_audio(args.audio, args.output, args.device)
            fallback_time = time.time() - step_start
            separate_time = 0
            vocals_time = 0
            no_vocals_time = 0
            merge_time = 0
            note_count = -1  # 未知

        total_time = time.time() - total_start

        # 报告结果
        print("\n" + "=" * 50)
        print("推理完成！")
        print(f"输出MIDI: {args.output}")
        if note_count >= 0:
            print(f"最终音符数: {note_count}")
        print(f"总耗时: {total_time:.1f}s")
        if vocals_path and no_vocals_path:
            print(f"  分离耗时: {separate_time:.1f}s")
            print(f"  人声转录耗时: {vocals_time:.1f}s")
            print(f"  伴奏转录耗时: {no_vocals_time:.1f}s")
            print(f"  合并耗时: {merge_time:.1f}s")
        print("=" * 50)


if __name__ == "__main__":
    main()
