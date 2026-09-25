from pathlib import Path

import psutil

root = Path(__file__).resolve().parent
pid_file = root / '.runtime' / 'backend.pid'
if not pid_file.exists():
    raise SystemExit('No background server PID recorded. Use Ctrl+C in the run.bat window.')
try:
    process = psutil.Process(int(pid_file.read_text(encoding='utf-8-sig').strip()))
    if str(root / 'custom_app.py').lower() not in [arg.lower() for arg in process.cmdline()]:
        raise SystemExit('PID belongs to another process; nothing stopped.')
    processes = process.children(recursive=True) + [process]
    for child in processes:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=10)
    if alive:
        raise SystemExit('Some server processes are still running.')
except psutil.NoSuchProcess:
    pass
pid_file.unlink(missing_ok=True)
print('Background server stopped.')
