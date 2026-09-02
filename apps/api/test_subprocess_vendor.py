import subprocess
completed = subprocess.run(
    ["/home/ahnaf-zakaria/Desktop/BCOL/creatorproof/apps/api/vendor/ClipBased-SyntheticImageDetection/.venv/bin/python", "-c", "import sys; print('EXEC:', sys.executable); print('PATH:', sys.path)"],
    cwd="/home/ahnaf-zakaria/Desktop/BCOL/creatorproof/apps/api/vendor/ClipBased-SyntheticImageDetection",
    capture_output=True,
    text=True
)
print(completed.stdout)
