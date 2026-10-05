"""Find and replace outdated mzmine screenshots in the documentation.

Many pages still show screenshots of mzmine versions older than mzmine 4. This
script keeps track of them and helps to swap them for new ones:

    python scripts/screenshots.py list [-s TEXT]          outdated screenshots and their pages
    python scripts/screenshots.py scan [--unlisted]       all images last changed before mzmine 4
    python scripts/screenshots.py replace OLD NEW         put a new screenshot in place of OLD
    python scripts/screenshots.py gallery                 HTML page with all outdated screenshots

The outdated screenshots are listed in ``scripts/outdated_screenshots.csv``.
They were found by taking every image whose content was last changed before the
mzmine 4.0.0 release (2024-04-11) and checking it by eye: the old bar-chart
window icon, the dialog title "Please set the parameters", "MZmine 3" or
"MZmine 2" branding or the old grey checkboxes mark a screenshot as outdated.
``replace`` removes an image from the list once it has been exchanged.

Only the Python standard library and git are needed.
"""

import argparse
import csv
import html
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MANIFEST = ROOT / "scripts" / "outdated_screenshots.csv"
MZMINE4_RELEASE = "2024-04-11"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
SITE = "https://mzmine.github.io/mzmine_documentation/latest/"

# image references in markdown pages: ![alt](path "title"), <img src="path">, [id]: path
REFERENCE_PATTERNS = [
    re.compile(r"!\[[^\]]*\]\(\s*<?(?P<ref>[^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)"),
    re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"'](?P<ref>[^\"']+)[\"']", re.IGNORECASE),
    re.compile(r"^[ \t]*\[[^\]]+\]:[ \t]*<?(?P<ref>[^\s>]+)>?", re.MULTILINE),
]


# ---------------------------------------------------------------------------
# repository helpers


def rel(path):
    """Path relative to the repository root, with forward slashes."""
    return Path(path).resolve().relative_to(ROOT).as_posix()


def normalize(posix_path):
    """Resolve '.' and '..' in a repository-relative posix path."""
    parts = []
    for part in PurePosixPath(posix_path).parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts)


def all_images():
    return sorted(rel(p) for p in DOCS.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES and p.is_file())


def markdown_pages():
    return sorted(DOCS.rglob("*.md"))


def find_references():
    """Return {image path: [(page path, raw reference), ...]} for all markdown pages."""
    refs = defaultdict(list)
    for page in markdown_pages():
        text = page.read_text(encoding="utf-8", errors="replace")
        page_dir = PurePosixPath(rel(page)).parent
        for pattern in REFERENCE_PATTERNS:
            for match in pattern.finditer(text):
                raw = match.group("ref")
                if re.match(r"^[a-z][a-z0-9+.-]*:", raw, re.IGNORECASE) or raw.startswith("#"):
                    continue  # URL, data: URI or anchor
                target = normalize(str(page_dir / re.split(r"[?#]", raw)[0]))
                refs[target].append((rel(page), raw))
    return refs


def last_changed(image):
    """Date of the last commit that added or modified the file content (renames do not count)."""
    out = subprocess.run(
        ["git", "log", "--follow", "--diff-filter=AM", "-1", "--format=%ad", "--date=short", "--", image],
        cwd=ROOT, capture_output=True, text=True, check=False)
    return out.stdout.strip() or "uncommitted"


def nav_pages():
    pages = set()
    for line in (ROOT / "mkdocs.yml").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = re.search(r":\s+([\w./-]+\.md)\s*$", line)
        if match:
            pages.add("docs/" + match.group(1))
    return pages


# ---------------------------------------------------------------------------
# manifest


def read_manifest():
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open(encoding="utf-8", newline="") as f:
        return {row["image"]: row for row in csv.DictReader(f)}


def write_manifest(entries):
    with MANIFEST.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["image", "status", "evidence"], lineterminator="\n")
        writer.writeheader()
        for image in sorted(entries, key=str.lower):
            row = entries[image]
            writer.writerow({"image": image, "status": row.get("status", ""), "evidence": row.get("evidence", "")})


def resolve_image(name, candidates):
    """Accept a repository path, a path inside docs/ or a unique file name."""
    name = name.replace("\\", "/")
    for option in (name, "docs/" + name, normalize(name)):
        if option in candidates:
            return option
    path = Path(name)
    if path.exists():
        try:
            if rel(path) in candidates:
                return rel(path)
        except ValueError:
            pass
    matches = [c for c in candidates if c.lower().endswith("/" + name.lower()) or c.lower() == name.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"error: no image matches '{name}'")
    sys.exit(f"error: '{name}' is ambiguous, use the full path:\n  " + "\n  ".join(matches))


# ---------------------------------------------------------------------------
# output


def matches_search(row, search):
    if not search:
        return True
    haystack = " ".join(str(v) for v in row.values()).lower()
    return all(term in haystack for term in search.lower().split())


def print_rows(rows, columns, fmt):
    if fmt == "json":
        print(json.dumps(rows, indent=2))
        return
    if fmt == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows([{k: "; ".join(v) if isinstance(v, list) else v for k, v in r.items()} for r in rows])
        return
    for row in rows:
        head = "  ".join(f"{row[c]}" for c in columns if c not in ("image", "pages"))
        print(f"{row['image']}\n    {head}")
        for page in row["pages"] or ["(not used on any page)"]:
            print(f"    -> {page}")


# ---------------------------------------------------------------------------
# commands


def cmd_list(args):
    manifest = read_manifest()
    refs = find_references()
    rows = []
    for image, entry in sorted(manifest.items()):
        pages = sorted({page for page, _ in refs.get(image, [])})
        row = {"image": image, "status": entry["status"], "evidence": entry["evidence"], "pages": pages}
        if args.status and entry["status"] != args.status:
            continue
        if args.page and not any(args.page.lower() in p.lower() for p in pages):
            continue
        if not matches_search(row, args.search):
            continue
        if args.dates:
            row["last_changed"] = last_changed(image)
        rows.append(row)
    columns = ["image", "status", "evidence"] + (["last_changed"] if args.dates else []) + ["pages"]
    print_rows(rows, columns, args.format)
    if args.format == "table":
        pages = {p for r in rows for p in r["pages"]}
        print(f"\n{len(rows)} outdated screenshot(s) on {len(pages)} page(s)")


def cmd_scan(args):
    manifest = read_manifest()
    refs = find_references()
    rows = []
    images = all_images()
    for n, image in enumerate(images, 1):
        if args.search and args.search.lower() not in image.lower():
            continue
        if args.unlisted and image in manifest:
            continue
        print(f"\rchecking git history {n}/{len(images)}", end="", file=sys.stderr)
        date = last_changed(image)
        if date != "uncommitted" and date >= args.before:
            continue
        pages = sorted({page for page, _ in refs.get(image, [])})
        if args.used and not pages:
            continue
        rows.append({"image": image, "last_changed": date,
                     "listed": manifest[image]["status"] if image in manifest else "-", "pages": pages})
    print(file=sys.stderr)
    print_rows(rows, ["image", "last_changed", "listed", "pages"], args.format)
    if args.format == "table":
        print(f"\n{len(rows)} image(s) last changed before {args.before}; "
              f"'listed' shows the status in {rel(MANIFEST)}")


def update_references(old, new, refs, dry_run):
    """Point every reference to `old` at `new`. Returns the changed pages."""
    changed = []
    by_page = defaultdict(set)
    for page, raw in refs.get(old, []):
        by_page[page].add(raw)
    for page, raws in sorted(by_page.items()):
        path = ROOT / page
        with path.open(encoding="utf-8", newline="") as f:  # keep the line endings of the page
            text = f.read()
        page_dir = PurePosixPath(page).parent
        new_text = text
        for raw in raws:
            suffix = raw[len(re.split(r"[?#]", raw)[0]):]  # keep ?query or #anchor
            new_ref = posixpath.relpath(new, page_dir.as_posix()) + suffix
            for pattern in REFERENCE_PATTERNS:
                new_text = pattern.sub(
                    lambda m: m.group(0).replace(raw, new_ref) if m.group("ref") == raw else m.group(0),
                    new_text)
        if new_text != text:
            changed.append(page)
            if not dry_run:
                with path.open("w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
    return changed


def cmd_replace(args):
    images = all_images()
    old = resolve_image(args.old, images)
    new_file = Path(args.new)
    if not new_file.is_file():
        sys.exit(f"error: new screenshot '{args.new}' not found")
    if new_file.suffix.lower() not in IMAGE_SUFFIXES:
        sys.exit(f"error: '{new_file.name}' is not an image ({', '.join(sorted(IMAGE_SUFFIXES))})")

    old_path = PurePosixPath(old)
    if args.name:
        target = str(old_path.parent / args.name)
    elif new_file.suffix.lower() == old_path.suffix.lower():
        target = old  # same format: overwrite, the pages stay as they are
    else:
        target = str(old_path.with_suffix(new_file.suffix.lower()))
    if target != old and (ROOT / target).exists() and not args.force:
        sys.exit(f"error: {target} already exists, use --force to overwrite it")

    refs = find_references()
    prefix = "[dry run] " if args.dry_run else ""
    pages = sorted({page for page, _ in refs.get(old, [])})
    changed = update_references(old, target, refs, args.dry_run) if target != old else []

    if not args.dry_run:
        (ROOT / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(new_file, ROOT / target)
        if target != old:
            (ROOT / old).unlink()

    print(f"{prefix}{old} -> {target}")
    print(f"{prefix}used on {len(pages)} page(s): {', '.join(pages) if pages else '-'}")
    if target != old:
        print(f"{prefix}updated references in: {', '.join(changed) if changed else '-'}")

    manifest = read_manifest()
    if old in manifest and not args.keep_listed:
        del manifest[old]
        if not args.dry_run:
            write_manifest(manifest)
        print(f"{prefix}removed from {rel(MANIFEST)} ({len(manifest)} left)")


def cmd_gallery(args):
    manifest = read_manifest()
    refs = find_references()
    nav = nav_pages()
    out = Path(args.output).resolve()
    by_page = defaultdict(list)
    for image, entry in manifest.items():
        for page in sorted({page for page, _ in refs.get(image, [])}) or ["(not used on any page)"]:
            by_page[page].append((image, entry))
    pages = sorted(by_page, key=lambda p: (-len(by_page[p]), p))

    def link(target):
        return html.escape(os.path.relpath(ROOT / target, out.parent).replace(os.sep, "/"))

    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Outdated screenshots</title>
<style>
body{{margin:0;background:#f6f7f9;color:#1d2330;font:14px/1.45 system-ui,"Segoe UI",Arial,sans-serif}}
header,nav,main{{max-width:1200px;margin:auto;padding:0 16px}} header{{padding-top:20px}}
h1{{font-size:20px;margin:0 0 4px}} header p{{margin:0;color:#5f6b7a}}
nav{{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}
nav a{{font-size:12px;padding:3px 8px;border:1px solid #dde2e8;border-radius:999px;background:#fff;color:inherit;text-decoration:none}}
section{{margin-top:22px}} h2{{font-size:15px;margin:0 0 8px}} h2 a{{color:inherit}}
h2 small{{font-weight:400;color:#5f6b7a}} .nonav{{color:#b42318}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}}
figure{{margin:0;background:#fff;border:1px solid #dde2e8;border-radius:8px;overflow:hidden}}
figure a{{display:flex;align-items:center;justify-content:center;background:#eceff3;height:230px}}
figure img{{max-width:100%;max-height:230px;object-fit:contain}}
figcaption{{padding:8px 10px;font-size:12px;color:#5f6b7a}} figcaption b{{color:#1d2330;word-break:break-all}}
code{{font-size:11px;background:#eef1f4;padding:1px 4px;border-radius:3px;word-break:break-all}}
.tag{{font-size:11px;font-weight:600;padding:1px 6px;border-radius:4px;margin-right:4px;color:#b42318;background:#fde8e7}}
.likely{{color:#8a5a00;background:#fff3d6}}
</style></head><body><header><h1>Outdated mzmine screenshots</h1>
<p>{len(manifest)} screenshot(s) from <code>{rel(MANIFEST)}</code> on {len(pages)} page(s).
Exchange one with <code>python scripts/screenshots.py replace &lt;image&gt; &lt;new screenshot&gt;</code>.</p>
</header><nav>"""]
    for page in pages:
        anchor = re.sub(r"[^A-Za-z0-9]+", "-", page)
        parts.append(f'<a href="#{anchor}">{html.escape(page.removeprefix("docs/"))} ({len(by_page[page])})</a>')
    parts.append("</nav><main>")
    for page in pages:
        anchor = re.sub(r"[^A-Za-z0-9]+", "-", page)
        if page.startswith("docs/"):
            url = SITE + page.removeprefix("docs/").removesuffix(".md") + ".html"
            title = f'<a href="{html.escape(url)}" target="_blank">{html.escape(page.removeprefix("docs/"))}</a>'
            if page not in nav:
                title += ' <small class="nonav">not in nav</small>'
            title += f' <small>· <a href="{link(page)}">source</a></small>'
        else:
            title = html.escape(page)
        parts.append(f'<section id="{anchor}"><h2>{title}</h2><div class="grid">')
        for image, entry in by_page[page]:
            status = entry["status"]
            parts.append(
                f'<figure><a href="{link(image)}" target="_blank"><img loading="lazy" src="{link(image)}" '
                f'alt="{html.escape(PurePosixPath(image).name)}"></a><figcaption>'
                f'<span class="tag {html.escape(status)}">{html.escape(status)}</span>'
                f'<b>{html.escape(PurePosixPath(image).name)}</b><br>{html.escape(entry["evidence"])}<br>'
                f'<code>{html.escape(image)}</code></figcaption></figure>')
        parts.append("</div></section>")
    parts.append("</main></body></html>")
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out} ({len(manifest)} screenshots, {len(pages)} pages)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="search the list of outdated screenshots")
    p.add_argument("-s", "--search", help="words that must appear in the image path, page or evidence")
    p.add_argument("-p", "--page", help="only screenshots used on pages whose path contains this text")
    p.add_argument("--status", choices=["old", "likely"], help="only this status")
    p.add_argument("--dates", action="store_true", help="also show when each image was last changed")
    p.add_argument("-f", "--format", choices=["table", "csv", "json"], default="table")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("scan", help="find all images last changed before a date (default: mzmine 4 release)")
    p.add_argument("--before", default=MZMINE4_RELEASE, help=f"cut-off date YYYY-MM-DD (default {MZMINE4_RELEASE})")
    p.add_argument("-s", "--search", help="only images whose path contains this text")
    p.add_argument("--unlisted", action="store_true", help=f"skip images already in {MANIFEST.name}")
    p.add_argument("--used", action="store_true", help="skip images that no page uses")
    p.add_argument("-f", "--format", choices=["table", "csv", "json"], default="table")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("replace", help="put a new screenshot in place of an old one")
    p.add_argument("old", help="image to replace: repository path, path inside docs/ or unique file name")
    p.add_argument("new", help="the new screenshot file")
    p.add_argument("--name", help="new file name in the same folder (default: keep the old name)")
    p.add_argument("--keep-listed", action="store_true", help=f"keep the image in {MANIFEST.name}")
    p.add_argument("--force", action="store_true", help="overwrite an existing file with the new name")
    p.add_argument("-n", "--dry-run", action="store_true", help="only show what would change")
    p.set_defaults(func=cmd_replace)

    p = sub.add_parser("gallery", help="write an HTML page showing all outdated screenshots")
    p.add_argument("-o", "--output", default=str(ROOT / "outdated_screenshots.html"),
                   help="output file (default: outdated_screenshots.html in the repository root)")
    p.set_defaults(func=cmd_gallery)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
