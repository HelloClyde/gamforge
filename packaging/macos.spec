# A native onedir .app. The console bootloader also supports captured workers;
# Finder opens the same executable with no arguments, which launches the GUI.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from a9288 import __version__

root = Path(SPECPATH).parent
helper = root / 'src/a9288/data/bin/native-boot'
data = [item for item in collect_data_files('a9288')
        if Path(item[0]).parent.name != 'bin']
a = Analysis([str(root / 'packaging/entry.py')], pathex=[str(root / 'src')],
             datas=data, binaries=[(str(helper), 'a9288/data/bin')],
             hiddenimports=collect_submodules('a9288'),
             excludes=['pytest', 'ruff', 'py65', 'setuptools', 'pip'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='GAMForge',
          console=True, debug=False, strip=False, upx=False,
          target_arch=os.environ['GAMFORGE_MAC_ARCH'], codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='GAMForge-runtime')
app = BUNDLE(coll, name='GAMForge.app', version=__version__,
             bundle_identifier='io.github.HelloClyde.GAMForge',
             info_plist={'CFBundleDisplayName': 'GAMForge',
                         'CFBundleShortVersionString': __version__,
                         'LSMinimumSystemVersion': os.environ['GAMFORGE_MAC_MINIMUM'],
                         # A console bootloader is needed for captured workers,
                         # but Finder must launch a normal foreground GUI app.
                         'LSBackgroundOnly': False,
                         'NSHighResolutionCapable': True,
                         'NSPrincipalClass': 'NSApplication'})
