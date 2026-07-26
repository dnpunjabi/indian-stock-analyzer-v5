import shutil
import os

sync_targets = [
    ('backend/static/index.html', 'android/app/src/main/assets/public/index.html'),
    ('backend/static/index.html', 'android/app/build/intermediates/assets/debug/public/index.html'),
    ('backend/static/app.js', 'android/app/src/main/assets/public/app.js'),
    ('backend/static/app.js', 'android/app/build/intermediates/assets/debug/public/app.js'),
    ('backend/static/modernizer.js', 'android/app/src/main/assets/public/modernizer.js'),
    ('backend/static/modernizer.js', 'android/app/build/intermediates/assets/debug/public/modernizer.js'),
    ('backend/static/modernizer.css', 'android/app/src/main/assets/public/modernizer.css'),
    ('backend/static/modernizer.css', 'android/app/build/intermediates/assets/debug/public/modernizer.css'),
]

for src, dst in sync_targets:
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print(f"Synced {src} -> {dst}")
    else:
        print(f"Source not found: {src}")
