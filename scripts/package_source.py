"""Package source, locked dependencies, screenshots and reports; exclude runtime state."""
from pathlib import Path
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
excluded = {'.git','.venv','node_modules','.next','__pycache__','.pytest_cache','var','artifacts','test-results','coverage'}
def eligible(path):
    relative = path.relative_to(root)
    return not any(part in excluded for part in relative.parts) and path.name != '.env' and path.suffix not in {'.pyc','.tsbuildinfo','.log','.sqlite3','.db'}

tree_path = root/'docs/repository-tree.txt'
tree_path.touch(exist_ok=True)
paths = sorted(p for p in root.rglob('*') if eligible(p))
tree = ['meridian/']
for path in paths:
    relative = path.relative_to(root)
    tree.append('  '*len(relative.parts) + path.name + ('/' if path.is_dir() else ''))
tree_path.write_text('\n'.join(tree)+'\n')
output = root.parent/'deliverables/meridian-prototype.zip'; output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for path in sorted(paths):
        if path.is_file(): archive.write(path,Path('meridian')/path.relative_to(root))
        elif path.is_dir(): archive.writestr(str(Path('meridian')/path.relative_to(root))+'/',b'')
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    files = [name for name in archive.namelist() if not name.endswith('/')]
    assert 'meridian/README.md' in files
    assert 'meridian/frontend/generated/api.ts' in files
    assert not any('node_modules/' in name or '/var/' in name or name.endswith('.env') for name in files)
print(json.dumps({'file':str(output),'files':len(files),'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()},indent=2))
