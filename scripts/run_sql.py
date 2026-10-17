"""Execute a trusted local SQL file using the shared connection setting."""
import argparse
from pathlib import Path
from docker_db import execute

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    print(execute(args.file.read_text(encoding='utf-8')))
