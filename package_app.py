"""Create a shareable ZIP without local records, credentials, or bytecode."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parent
target = root.parent / 'Hookem_Attendance.zip'
with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
    for source in sorted(root.rglob('*')):
        relative = source.relative_to(root)
        if not source.is_file() or any(part in {'data', '__pycache__', '.git', 'bin'} for part in relative.parts):
            continue
        if source.suffix in {'.sqlite3', '.db', '.pyc', '.log'}:
            continue
        archive.write(source, Path('attendance_app') / relative)
with ZipFile(target) as archive:
    assert archive.testzip() is None
    assert 'attendance_app/vendor/qrcode/__init__.py' in archive.namelist()
    assert 'attendance_app/START_WINDOWS.bat' in archive.namelist()
    assert not any('/data/' in name for name in archive.namelist())
print(f'Created {target} ({target.stat().st_size:,} bytes)')
