import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("-exclude", help="Exclude prefix", required=False, default="")
parser.add_argument("-dir", help="Current directory", required=True)

directory = parser.parse_args().dir
exclude_prefixes = [parser.parse_args().exclude, f"{directory}/build"]
supported_extensions = [ ".h", ".hpp", ".hcc", ".c", ".cc", ".cpp", ".cxx"]

for path in Path(directory).rglob('*.*'):
    p = str(path.resolve())
    if p.endswith(tuple(supported_extensions)) and not p.startswith(tuple(exclude_prefixes)):
        print(p)