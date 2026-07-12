import ctypes, tempfile, os, pretty_midi, time

# Close any existing MCI device
ctypes.windll.winmm.mciSendStringW('close splashmidi', None, 0, None)

# Use unique filename
midi_path = os.path.join(tempfile.gettempdir(), 'pianoscribe_splash_new.mid')

pm = pretty_midi.PrettyMIDI()
piano = pretty_midi.Instrument(program=0)
melody = [(74,0.0,0.5),(69,0.5,0.5),(71,1.0,0.5),(66,1.5,0.5),(67,2.0,0.5),(62,2.5,0.5),(67,3.0,0.5),(69,3.5,1.5)]
for pitch, start, dur in melody:
    piano.notes.append(pretty_midi.Note(velocity=75, pitch=pitch, start=start, end=start+dur))
bass = [(50,0.0,2.0),(45,2.0,2.0),(43,4.0,1.0)]
for pitch, start, dur in bass:
    piano.notes.append(pretty_midi.Note(velocity=60, pitch=pitch, start=start, end=start+dur))
pm.instruments.append(piano)

pm.write(midi_path)
print(f'MIDI written to {midi_path}')
print(f'File size: {os.path.getsize(midi_path)} bytes')

r1 = ctypes.windll.winmm.mciSendStringW(f'open "{midi_path}" type sequencer alias splashmidi', None, 0, None)
print(f'MCI open result: {r1}')
r2 = ctypes.windll.winmm.mciSendStringW('play splashmidi', None, 0, None)
print(f'MCI play result: {r2}')
time.sleep(4)
r3 = ctypes.windll.winmm.mciSendStringW('close splashmidi', None, 0, None)
print(f'MCI close result: {r3}')
print('Done')
