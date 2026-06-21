"""Use ByteDance's pretrained model to transcribe audio - with librosa fix."""
import os
import sys
import numpy as np
import librosa
import torch

def transcribe_with_bytedance(audio_path, output_midi_path, device='cuda'):
    """Transcribe using ByteDance's pretrained model."""
    from piano_transcription_inference import PianoTranscription, sample_rate
    
    print(f"Loading audio: {audio_path}")
    # Load audio with librosa directly (bypass broken load_audio)
    audio, sr = librosa.load(audio_path, sr=sample_rate, mono=True)
    print(f"Audio duration: {len(audio)/sample_rate:.1f}s, SR: {sr}")
    
    print(f"Transcribing with ByteDance model on {device}...")
    # Use local checkpoint path
    checkpoint_path = r"c:\Users\Administrator\Desktop\乐谱生成\新建文件夹\CRNN_note_F1=0.9677_pedal_F1=0.9186 (1).pth"
    transcriptor = PianoTranscription(device=device, checkpoint_path=checkpoint_path)
    transcribed_dict = transcriptor.transcribe(audio, output_midi_path)
    
    print(f"Done! MIDI saved to: {output_midi_path}")
    
    # Print stats
    if 'onset' in transcribed_dict:
        print(f"Detected {len(transcribed_dict['onset'])} onsets")
    if 'note' in transcribed_dict:
        notes = transcribed_dict['note']
        print(f"Detected {len(notes)} notes")
        if notes:
            pitches = [n['midi_note'] for n in notes]
            print(f"Pitch range: {min(pitches)} - {max(pitches)}")
    
    return transcribed_dict

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio_path', type=str, required=True)
    parser.add_argument('--output_midi_path', type=str, default=None)
    parser.add_argument('--device', type=str, default='cuda')
    args = parser.parse_args()
    
    if args.output_midi_path is None:
        args.output_midi_path = args.audio_path.rsplit('.', 1)[0] + '_bytedance.mid'
    
    transcribe_with_bytedance(args.audio_path, args.output_midi_path, args.device)
