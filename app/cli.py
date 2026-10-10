"""Command-line entry points.

    python -m app.cli ocr samples/receipt_2.jpeg [--ocr-on-crop] [--save-crop out.jpg] [--json]
    python -m app.cli process samples/ [--out results.json] [--with-ocr-text]
    python -m app.cli process samples/ --save [--force]      # store in data/bills.db
    python -m app.cli list [--status needs_review] [--category Food] [--from 2026-09-01]
    python -m app.cli show 3
    python -m app.cli export --out backup.json
    python -m app.cli check                                   # is everything installed and working?
    python -m app.cli serve [--lan]                           # start the web app
"""

import argparse
import json
import sys
from pathlib import Path

import cv2


def cmd_ocr(args: argparse.Namespace) -> int:
    from app.pipeline.ocr_rapid import run_ocr
    from app.pipeline.preprocess import preprocess

    for path in args.images:
        prep = preprocess(path, ocr_on_crop=args.ocr_on_crop or None)
        result = run_ocr(prep.for_ocr, version=args.version, model_type=args.model_type, engine=args.engine)
        if args.save_crop:
            cv2.imwrite(str(args.save_crop), prep.cropped)
        if args.json:
            print(json.dumps({
                "image": str(path),
                "preprocess": {"crop_method": prep.crop_method, "receipt_fraction": prep.receipt_fraction,
                               "rotation_deg": prep.rotation_deg, "quality_warnings": prep.quality.warnings,
                               "seconds": prep.seconds},
                "ocr": result.to_dict(),
            }, indent=2, ensure_ascii=False))
            continue
        print(f"===== {path}")
        print(f"preprocess: {prep.crop_method}, receipt {prep.receipt_fraction:.0%} of photo, "
              f"rotated {prep.rotation_deg}°, quality warnings {prep.quality.warnings or 'none'}, {prep.seconds:.2f}s")
        print(f"ocr: {result.engine}, confidence {result.mean_confidence:.3f}, "
              f"extra rotation {result.rotation_deg}°, {result.seconds:.2f}s")
        print("-" * 60)
        print(result.text)
    return 0


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _image_paths(inputs: list[Path]) -> list[Path]:
    paths = []
    for p in inputs:
        if p.is_dir():
            paths += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
        else:
            paths.append(p)
    return paths


def cmd_process(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.llm.client import LLMError, warm_up
    from app.llm.prompts import EXTRACTION_SYSTEM
    from app.pipeline.run import process_image

    paths = _image_paths(args.images)
    if not paths:
        print("No images found.", file=sys.stderr)
        return 1
    model = get_settings().extract_model
    try:
        print(f"Loading {model}... {warm_up(model, EXTRACTION_SYSTEM):.1f}s", file=sys.stderr)
    except LLMError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.save:
        return _process_and_save(paths, force=args.force)

    results, failed = {}, 0
    for path in paths:
        print(f"Processing {path.name}...", file=sys.stderr)
        try:
            result = process_image(path).to_dict()
        except (LLMError, ValueError) as error:
            print(f"  FAILED: {error}", file=sys.stderr)
            failed += 1
            continue
        if not args.with_ocr_text:
            result.pop("ocr_text")
        results[path.name] = result
        warnings = ", ".join(w["code"] for w in result["warnings"]) or "none"
        print(f"  {result['status']} in {result['timings']['total_s']}s — {result['vendor']}, "
              f"total {result['total']}, {len(result['items'])} item(s), warnings: {warnings}", file=sys.stderr)

    output = json.dumps(results, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"Saved: {args.out}", file=sys.stderr)
    else:
        print(output)
    return 1 if failed else 0


def _process_and_save(paths: list[Path], *, force: bool) -> int:
    from app.db import repo
    from app.db.database import connect
    from app.ingest import ingest_file

    conn = connect()
    failed = 0
    for path in paths:
        print(f"{path.name}: ", end="", file=sys.stderr, flush=True)
        registered, status = ingest_file(conn, path, force=force)
        if registered.already_processed:
            print(f"already stored as receipt #{registered.receipt_id} ({status}); use --force to redo",
                  file=sys.stderr)
            continue
        failed += status == "failed"
        r = repo.get_receipt(conn, registered.receipt_id)
        detail = r["error"] if status == "failed" else (
            f"{r['vendor']}, total {r['total']}, {len(r['items'])} item(s), "
            f"warnings: {', '.join(w['code'] for w in r['warnings']) or 'none'}")
        print(f"#{registered.receipt_id} {status} - {detail}", file=sys.stderr)
    return 1 if failed else 0


def cmd_list(args: argparse.Namespace) -> int:
    from app.db import repo
    from app.db.database import connect

    rows = repo.list_receipts(connect(), status=args.status, vendor=args.vendor, category=args.category,
                              date_from=args.date_from, date_to=args.date_to, search=args.search)
    if not rows:
        print("No receipts.")
        return 0
    print(f"{'#':>4}  {'date':10}  {'vendor':30}  {'total':>10}  {'items':>5}  status")
    for r in rows:
        total = f"{r['total']:.2f}" if r["total"] is not None else "-"
        print(f"{r['id']:>4}  {r['date'] or '-':10}  {(r['vendor'] or '-')[:30]:30}  {total:>10}  "
              f"{r['item_count']:>5}  {r['status']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    from app.db import repo
    from app.db.database import connect

    record = repo.get_receipt(connect(), args.id)
    if record is None:
        print(f"Receipt {args.id} not found.", file=sys.stderr)
        return 1
    if not args.with_ocr_text:
        record.pop("ocr_text_rapid", None)
        record.pop("ocr_text_vlm", None)
    record.pop("extraction_raw", None)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """All stored receipts as JSON, keyed by original filename (also the eval prediction format)."""
    from app.db import repo
    from app.db.database import connect

    conn = connect()
    out = {}
    for row in repo.list_receipts(conn, limit=1_000_000):
        record = repo.get_receipt(conn, row["id"])
        record.pop("extraction_raw", None)
        out[record["original_filename"] or f"receipt_{record['id']}"] = record
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"Exported {len(out)} receipts to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Check every part the app needs; exit code 1 if something required is missing."""
    import platform
    import time

    import numpy as np

    from app.api.system import _ollama_status
    from app.config import get_settings
    from app.db.database import connect, schema_version
    from app.pipeline.ocr_rapid import run_ocr

    s = get_settings()
    problems = 0

    def report(ok: bool, what: str, detail: str = "", fix: str = "") -> None:
        nonlocal problems
        problems += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {what}" + (f": {detail}" if detail else ""))
        if not ok and fix:
            print(f"       -> {fix}")

    print("Checking Chat With Your Bills...")
    version = platform.python_version()
    report(sys.version_info >= (3, 12), "Python", version, "Install Python 3.14 from python.org")

    try:
        conn = connect(s.db_path)
        report(True, "Database", f"{s.db_path} (schema version {schema_version(conn)})")
        conn.close()
    except Exception as error:  # noqa: BLE001 - report any failure
        report(False, "Database", str(error), f"Check that {s.db_path.parent} is writable")

    # A tiny test image; the first run also downloads the OCR model files.
    image = np.full((80, 360, 3), 255, np.uint8)
    cv2.putText(image, "TOTAL 12.50", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    try:
        started = time.perf_counter()
        text = run_ocr(image).text
        ok = "12.50" in text
        report(ok, "OCR (RapidOCR)", f"read '{text.strip()}' in {time.perf_counter() - started:.1f} s",
               "Reinstall requirements: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
    except Exception as error:  # noqa: BLE001
        report(False, "OCR (RapidOCR)", str(error), "Reinstall requirements; the first run needs internet")

    status = _ollama_status()
    report(status["reachable"], "Ollama", status["host"] if status["reachable"] else status.get("error", ""),
           "Install Ollama from https://ollama.com and start it")
    for role, model in status.get("models", {}).items():
        required = role == "extract"
        label = "Extraction model" if required else "Vision model (second reading)"
        if model["installed"] or required:
            report(model["installed"], label, model["name"], f"ollama pull {model['name']}")
        else:
            print(f"  WARN {label}: {model['name']} not installed -> ollama pull {model['name']}")

    print("All checks passed." if not problems else f"{problems} problem(s) found.")
    return 1 if problems else 0


def cmd_serve(args: argparse.Namespace) -> int:
    import os
    import secrets

    import uvicorn

    from app.config import get_settings

    if args.log_file:
        # Started in the background (scripts/start.ps1): all output goes to the log file.
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        log = open(args.log_file, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - open while serving
        sys.stdout = sys.stderr = log

    os.environ["BILLS_PORT"] = str(args.port)
    host = "127.0.0.1"
    if args.lan:
        # A new random key each start: the phone needs the printed link (or the System page).
        os.environ["BILLS_LAN_KEY"] = secrets.token_urlsafe(9)
        host = "0.0.0.0"
    get_settings.cache_clear()

    from app import access
    print(f"\nOn this computer: http://127.0.0.1:{args.port}")
    if args.lan:
        links = access.phone_links()
        print("On your phone (same Wi-Fi), open:" if links else "No network address found; is Wi-Fi on?")
        for link in links:
            print(f"  {link}")
        print("Anyone with this link can see your receipts: use it only on a network you trust.\n")
    uvicorn.run("app.main:app", host=host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    ocr = sub.add_parser("ocr", help="preprocess + RapidOCR on one or more images")
    ocr.add_argument("images", nargs="+", type=Path)
    ocr.add_argument("--ocr-on-crop", action="store_true", help="give RapidOCR the cropped receipt")
    ocr.add_argument("--save-crop", type=Path)
    ocr.add_argument("--json", action="store_true")
    ocr.add_argument("--version", help="PP-OCRv4 | PP-OCRv5 | PP-OCRv6")
    ocr.add_argument("--model-type", help="tiny | small | medium | mobile | server")
    ocr.add_argument("--engine", help="onnxruntime | openvino")
    ocr.set_defaults(func=cmd_ocr)

    proc = sub.add_parser("process", help="full pipeline: image(s) or folder -> validated JSON")
    proc.add_argument("images", nargs="+", type=Path)
    proc.add_argument("--out", type=Path, help="write JSON to this file instead of the screen")
    proc.add_argument("--with-ocr-text", action="store_true", help="include the OCR text in the output")
    proc.add_argument("--save", action="store_true", help="store results in the database (data/bills.db)")
    proc.add_argument("--force", action="store_true", help="with --save: process again even if already stored")
    proc.set_defaults(func=cmd_process)

    lst = sub.add_parser("list", help="list stored receipts")
    lst.add_argument("--status", choices=["verified", "needs_review", "failed", "processing"])
    lst.add_argument("--vendor")
    lst.add_argument("--category")
    lst.add_argument("--from", dest="date_from", help="YYYY-MM-DD")
    lst.add_argument("--to", dest="date_to", help="YYYY-MM-DD")
    lst.add_argument("--search")
    lst.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="show one stored receipt as JSON")
    show.add_argument("id", type=int)
    show.add_argument("--with-ocr-text", action="store_true")
    show.set_defaults(func=cmd_show)

    export = sub.add_parser("export", help="export all stored receipts as JSON")
    export.add_argument("--out", type=Path)
    export.set_defaults(func=cmd_export)

    check = sub.add_parser("check", help="check that everything needed is installed and working")
    check.set_defaults(func=cmd_check)

    serve = sub.add_parser("serve", help="start the web app (http://127.0.0.1:8000)")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--lan", action="store_true",
                       help="also allow phones on the same Wi-Fi, with a random access key")
    serve.add_argument("--log-file", type=Path, help="write all output to this file (for background starts)")
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
