#!/usr/bin/env python3
"""ctxunbnd.py - Reconstruct files & directories from an LLM-readable text bundle."""
# Example (run from within bundle directory):  ./ctxunbnd.py context_files_collection.txt -o ./restored_project
# Example (run from outside bundle directory): ./ctxunbnd.py /path/to/context_files_collection.txt -o /path/to/restored_project

import argparse
import html
import re
import sys
from pathlib import Path, PurePosixPath


FILE_PATTERN = re.compile(r'<ctxbnd__file\s+path="([^"]+)">\n(.*?)</ctxbnd__file>\n\n', re.DOTALL)


# ✅ #4: Tightened path traversal protection
def safe_output_path(target_dir: Path, rel_path: str) -> Path:
    pure = PurePosixPath(rel_path)
    if pure.is_absolute():
        raise ValueError(f"absolute path not allowed: {rel_path}")
    if any(part in ("", ".", "..") for part in pure.parts):
        raise ValueError(f"unsafe path component in: {rel_path}")
    
    root = target_dir.resolve()
    candidate = (root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"path escapes target directory: {rel_path}")
    return candidate


def unpack_bundle(bundled_path: Path, target_dir: Path, force: bool = False, max_files: int | None = 20) -> tuple[int, int, int]:
    """Parse bundled file and write contents to target directory."""
    try:
        content = bundled_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Error reading bundle: {e}", file=sys.stderr)
        sys.exit(1)

    if "<ctxbnd" not in content:
        print("⚠️  Bundle does not appear to contain a <ctxbnd> root tag.", file=sys.stderr)
        
    matches = FILE_PATTERN.findall(content)
    
    # ✅ #3: Warn if no blocks found
    if not matches:
        print("⚠️  No file blocks found in bundle.", file=sys.stderr)

    created = 0
    skipped_existing = 0
    total_bytes = 0

    for escaped_path, file_content in matches:
        # ✅ #1: Clean max_files check using None for unlimited
        if max_files is not None and created >= max_files:
            break

        rel_path = html.unescape(escaped_path)
        
        try:
            resolved_target = safe_output_path(target_dir, rel_path)  # ✅ #4
        except ValueError as exc:
            print(f"⊘ Skipped unsafe path: {exc}", file=sys.stderr)
            continue

        if resolved_target.exists():
            if force:
                pass
            else:
                print(f"⊘ Skipped (exists): {rel_path} (use --force to overwrite)", file=sys.stderr)
                skipped_existing += 1
                continue

        try:
            resolved_target.parent.mkdir(parents=True, exist_ok=True)
            # ✅ #6: Unescape content before writing
            with resolved_target.open("w", encoding="utf-8", newline="") as f:
                f.write(file_content)
            
            created += 1
            total_bytes += len(resolved_target.read_bytes())
            
        except OSError as e:
            print(f"⊘ Failed to write {rel_path}: {e}", file=sys.stderr)

    return created, skipped_existing, total_bytes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unpack an LLM-readable text bundle into actual files."
    )
    parser.add_argument("bundle", help="Path to the concatenated .txt file")
    parser.add_argument("-o", "--output", default=".", 
                        help="Target directory for unpacked files (default: current dir)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files without prompting")
    
    # ✅ #1: Reject 0, use -1 for unlimited -> converts to None internally
    parser.add_argument("--max-files", type=int, default=20,
                        help="Maximum number of files to unpack (default: 20). Use -1 for unlimited.")

    args = parser.parse_args()

    if args.max_files == 0:
        parser.error("--max-files cannot be 0. Use a positive integer or -1 for unlimited.")

    bundled_path = Path(args.bundle).resolve()
    target_dir = Path(args.output).resolve()

    if not bundled_path.exists():
        print(f"Error: Bundle file '{bundled_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    max_files = None if args.max_files == -1 else args.max_files  # ✅ #1
    created, skipped_existing, total_bytes = unpack_bundle(bundled_path, target_dir, args.force, max_files)

    print(f"✅ Unpacked {created:,} files to '{target_dir}'", file=sys.stderr)
    print(f"Total size: {total_bytes:,} bytes", file=sys.stderr)

    if skipped_existing > 0 and not args.force:
        print(f"\n⚠️  Skipped {skipped_existing} existing file(s). Use --force to overwrite them.", file=sys.stderr)

    if max_files is not None and created >= max_files:
        print(f"\n⚠️  Reached --max-files limit ({args.max_files}). Use a higher value to pack more or -1 to disable check. Example: ./ctxunbnd.py context_files_collection.txt -o ./restored_project --max-files 32", file=sys.stderr)


if __name__ == "__main__":
    main()

