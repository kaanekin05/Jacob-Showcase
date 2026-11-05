"""Compare two APK or AAB archives entry by entry.

Usage: python3 -I apk_entry_diff.py OLD.apk NEW.apk

Prints entry counts, compressed totals, entries whose compressed size moved
by more than 50 KB, and the largest byte gaps between entries in each archive.
"""
import struct
import sys
import zipfile


def read_layout(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    infos = sorted(zipfile.ZipFile(path).infolist(), key=lambda i: i.header_offset)
    sizes = {i.filename: i.compress_size for i in infos}
    gaps = []
    for entry, following in zip(infos, infos[1:]):
        start = entry.header_offset
        name_len, extra_len = struct.unpack("<HH", raw[start + 26:start + 30])
        end = start + 30 + name_len + extra_len + entry.compress_size
        if following.header_offset > end:
            gaps.append((following.header_offset - end, entry.filename))
    return sizes, gaps


def main(old_path, new_path):
    old_sizes, old_gaps = read_layout(old_path)
    new_sizes, new_gaps = read_layout(new_path)
    print("entries", len(old_sizes), len(new_sizes))
    print("compressed totals", sum(old_sizes.values()), sum(new_sizes.values()))
    rows = []
    for name in set(old_sizes) | set(new_sizes):
        before = old_sizes.get(name, 0)
        after = new_sizes.get(name, 0)
        if abs(after - before) > 50000:
            rows.append((after - before, name, before, after))
    for row in sorted(rows):
        print("delta", row)
    for label, gaps in (("old", old_gaps), ("new", new_gaps)):
        for size, after in sorted(gaps, reverse=True)[:5]:
            print(label, "gap", size, "after", after)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
