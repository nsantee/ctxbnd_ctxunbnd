#!/usr/bin/env python3
"""ctxbnd.py - Pack a folder into an LLM-readable text bundle."""
# Example (run from within the target directory to pack): ./ctxbnd.py . 
# Example (run from outside the target directory):        ./ctxbnd.py /absolute/or/relative/path/to/dir

import argparse
import fnmatch
import html
import sys
from pathlib import Path


DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__",
    "node_modules", "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

DEFAULT_SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".sqlite", ".db",
}

DEFAULT_SKIP_FILES = {"context_files_collection.txt"}

RESERVED_FILE_DELIMITER = "</ctxbnd__file>\n\n"

def looks_binary(path: Path, sample_size: int = 4096) -> bool:
    """Return True if the file appears to be binary."""
    try:
        with path.open("rb") as f:
            sample = f.read(sample_size)
    except OSError:
        return True

    return b"\x00" in sample

def should_skip_file(path: Path, output_path: Path | None) -> bool:
    """Return True if this file should not be packed."""
    try:
        if output_path is not None and path.resolve() == output_path:
            return True
    except OSError:
        pass

    # ✅ Skip hardcoded bundle names to prevent recursive packing
    if path.name in DEFAULT_SKIP_FILES:
        return True

    if path.name.startswith("."):
        return True

    if path.suffix.lower() in DEFAULT_SKIP_SUFFIXES:
        return True

    if looks_binary(path):
        return True

    return False


def process_directory(
    dir_path: Path, base_dir: Path, out_stream, output_path: Path | None,
    max_size: int | None, exclude_patterns: list[str], files_packed: list[int], max_files: int | None
) -> tuple[int, int, int]:
    """Recursively traverse directory and write files with HTML-style tags."""
    
    packed = 0
    skipped = 0
    total_chars = 0

    try:
        entries = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
    except PermissionError:
        print(f"⊘ Skipped directory, permission denied: {dir_path}", file=sys.stderr)
        return packed, skipped, total_chars
    except OSError as exc:
        print(f"⊘ Skipped directory {dir_path}: {exc}", file=sys.stderr)
        return packed, skipped, total_chars

    for entry in entries:
        # ✅ #1: Clean max_files check using None for unlimited
        if max_files is not None and files_packed[0] >= max_files:
            break

        if entry.is_symlink():
            print(f"⊘ Skipped symlink: {entry.name}", file=sys.stderr)
            skipped += 1
            continue

        # ✅ #5: Compute rel_path early so exclude patterns apply to dirs too
        rel_path = entry.relative_to(base_dir).as_posix()
        if any(fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(entry.name, pat) for pat in exclude_patterns):
            print(f"⊘ Skipped (excluded): {rel_path}", file=sys.stderr)
            skipped += 1
            continue

        if entry.is_dir():
            if not (entry.name.startswith(".") or entry.name in DEFAULT_SKIP_DIRS):
                p, s, c = process_directory(entry, base_dir, out_stream, output_path, max_size, exclude_patterns, files_packed, max_files)
                packed += p
                skipped += s
                total_chars += c
            continue

        if not entry.is_file():
            continue

        if should_skip_file(entry, output_path):
            print(f"⊘ Skipped: {rel_path}", file=sys.stderr)
            skipped += 1
            continue

        try:
            stat_info = entry.stat()
            size_bytes = stat_info.st_size
            
            if max_size is not None and size_bytes > max_size:
                print(f"⊘ Skipped (too large): {entry.name} ({size_bytes:,} bytes)", file=sys.stderr)
                skipped += 1
                continue

            escaped_path = html.escape(rel_path, quote=True)
            with entry.open("r", encoding="utf-8", errors="replace", newline="") as f:
                content = f.read()
        except OSError as exc:
            print(f"⊘ Skipped file {entry.name}: {exc}", file=sys.stderr)
            skipped += 1
            continue

        if RESERVED_FILE_DELIMITER in content:
            print(
                f"⊘ Skipped (contains reserved ctxbnd delimiter): {rel_path}",
                file=sys.stderr,
            )
            skipped += 1
            continue
            
        # ctxbnd is optimized for readable LLM editing. Content is written raw.
        # Files containing the reserved closing delimiter are skipped.
        block = f'<ctxbnd__file path="{escaped_path}">\n{content}</ctxbnd__file>\n\n'
        out_stream.write(block)

        packed += 1
        files_packed[0] += 1
        total_chars += len(block)

    return packed, skipped, total_chars


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pack a directory into an LLM-readable text bundle."
    )
    parser.add_argument("directory", nargs="?", default=".")
    parser.add_argument("-o", "--output", default="context_files_collection.txt")
    parser.add_argument("--max-size", type=int, default=None, 
                        help="Skip files larger than this size in bytes (e.g., 5242880 for 5MB)")
    parser.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                        help="Glob pattern to skip files/dirs (can be used multiple times, e.g., '*.log' 'tests/*')")
    
    # ✅ #1: Reject 0, use -1 for unlimited -> converts to None internally
    parser.add_argument("--max-files", type=int, default=20,
                        help="Maximum number of files to pack (default: 20). Use -1 for unlimited.")

    args = parser.parse_args()

    if args.max_files == 0:
        parser.error("--max-files cannot be 0. Use a positive integer or -1 for unlimited.")

    dir_path = Path(args.directory).resolve()
    if not dir_path.is_dir():
        print(f"Error: '{dir_path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).resolve()
    max_files = None if args.max_files == -1 else args.max_files  # ✅ #1
    files_packed_counter = [0]

    try:
        with output_path.open("w", encoding="utf-8", newline="\n") as out_stream:
            # ✅ #7: Simplified header (removed source/timestamp for LLM friendliness)
            header = '<ctxbnd version="0.1">\n'
            out_stream.write(header)
            total_chars = len(header)
            
            packed, skipped, file_chars = process_directory(
                dir_path, dir_path, out_stream, output_path, args.max_size, 
                args.exclude, files_packed_counter, max_files
            )
            total_chars += file_chars
            
            # ✅ #7: Closing root tag
            footer = '</ctxbnd>\n'
            out_stream.write(footer)
            total_chars += len(footer)
    except OSError as exc:
        print(f"Error writing output file '{output_path}': {exc}", file=sys.stderr)
        sys.exit(1)

    estimated_tokens = total_chars // 4

    print(f"Packed files: {packed:,}", file=sys.stderr)
    print(f"Skipped files: {skipped:,}", file=sys.stderr)
    print(f"Output chars: {total_chars:,} (including metadata)", file=sys.stderr)
    print(f"Tokens: ~{estimated_tokens:,}", file=sys.stderr)

    if max_files is not None and files_packed_counter[0] >= max_files:
        print(f"\n⚠️ Reached --max-files limit ({args.max_files}). Use a higher value to pack more or -1 to disable check. Example: ./ctxbnd.py . --max-files 32", file=sys.stderr)


if __name__ == "__main__":
    main()

