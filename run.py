import subprocess
import sys


def run(cmd):
    print(f"\n>>> {cmd}")
    return subprocess.run(cmd, shell=True).returncode == 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    dry = "--dry-run" if "--dry-run" in sys.argv else ""

    if mode in ("scrape", "all"):
        run("python manage.py scrape_jobs")

    if mode in ("match", "all"):
        run("python manage.py match_jobs")

    if mode in ("apply", "all"):
        run(f"python manage.py apply_jobs {dry}".strip())

    print("\nDone.")
