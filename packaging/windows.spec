# Build GUI and console companion with a shared Python/runtime data directory.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root=Path(SPECPATH).parent
a=Analysis([str(root/'packaging/entry.py')],pathex=[str(root/'src')],
    datas=collect_data_files('a9288'),hiddenimports=collect_submodules('a9288'),
    excludes=['pytest','ruff','py65','setuptools','pip'],noarchive=False)
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='A9288-Converter',
        console=False,debug=False,strip=False,upx=False)
cli=EXE(pyz,a.scripts,[],exclude_binaries=True,name='A9288-CLI',
        console=True,debug=False,strip=False,upx=False)
coll=COLLECT(gui,cli,a.binaries,a.datas,strip=False,upx=False,name='A9288-Translator')
