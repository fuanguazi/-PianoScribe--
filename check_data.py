import os

# Check all subdirectories for .pt files
data_dir = r'D:\PianoTraining\data'
for root, dirs, files in os.walk(data_dir):
    pt_files = [f for f in files if f.endswith('.pt')]
    if pt_files:
        print(f'{root}: {len(pt_files)} .pt files')

# Also check if there are files directly in train/validation
for split in ['train', 'validation']:
    split_dir = os.path.join(data_dir, split)
    if os.path.exists(split_dir):
        all_files = os.listdir(split_dir)
        print(f'\n{split_dir}: {len(all_files)} total items')
        # Check subdirectories
        for item in all_files:
            item_path = os.path.join(split_dir, item)
            if os.path.isdir(item_path):
                sub_files = os.listdir(item_path)
                print(f'  {item}/: {len(sub_files)} files')
