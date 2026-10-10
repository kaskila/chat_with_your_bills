"""Score OCR text or extracted receipt data against the hand-checked ground truth.

Usage (from the project root):

    # OCR text: one .txt per receipt in a folder, or the legacy combined file
    python -m eval.run_eval ocr --name tesseract-legacy --legacy-file legacy/extracted_text.txt
    python -m eval.run_eval ocr --name some-engine --text-dir path/to/texts

    # OCR by running preprocessing + RapidOCR on the ground-truth images now
    python -m eval.run_eval ocr --name rapid-default --rapid
    python -m eval.run_eval ocr --name rapid-on-crop --rapid --ocr-on-crop
    python -m eval.run_eval ocr --name rapid-v5-server --rapid --version PP-OCRv5 --model-type server

    # Extraction: a JSON file {"receipt_1.jpeg": {...ReceiptData fields, "warnings": [...]}, ...}
    python -m eval.run_eval extraction --name legacy --predictions eval/results/legacy_predictions.json

Each run prints a summary and saves a report to eval/results/.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from eval.metrics import score_extraction, score_ocr, summarize_extraction, summarize_ocr


def load_ground_truth(gt_dir: Path | None = None) -> dict[str, dict]:
    """Return {image filename: ground truth}, with the reference transcription under "text"."""
    gt_dir = gt_dir or get_settings().ground_truth_dir
    truth = {}
    for path in sorted(gt_dir.glob("*.json")):
        gt = json.loads(path.read_text(encoding="utf-8"))
        txt = path.with_suffix(".txt")
        gt["text"] = txt.read_text(encoding="utf-8") if txt.exists() else None
        truth[gt["image"]] = gt
    return truth


def read_legacy_ocr(path: Path) -> dict[str, str]:
    """Split the old pipeline's combined file on its '-- Text from <file> --' markers."""
    texts = {}
    for section in path.read_text(encoding="utf-8").split("-- Text from ")[1:]:
        header, _, body = section.partition("\n")
        texts[header.removesuffix("--").strip()] = body.strip()
    return texts


def read_text_dir(path: Path) -> dict[str, str]:
    """Texts named after their image: receipt_1.jpeg.txt or receipt_1.txt."""
    texts = {}
    for txt in sorted(path.glob("*.txt")):
        stem = txt.name.removesuffix(".txt")
        texts[stem] = txt.read_text(encoding="utf-8")
    return texts


def run_rapid(truth: dict[str, dict], args: argparse.Namespace) -> tuple[dict[str, str], dict[str, dict]]:
    """Preprocess + RapidOCR each ground-truth image. Returns texts and per-image details."""
    from app.pipeline.ocr_rapid import get_engine, run_ocr
    from app.pipeline.preprocess import preprocess

    get_engine(args.version, args.model_type, args.engine)  # load models before timing
    samples = get_settings().samples_dir
    texts, details = {}, {}
    for image in truth:
        prep = preprocess(samples / image, ocr_on_crop=args.ocr_on_crop, shadows=args.shadows or None,
                          contrast=args.contrast)
        result = run_ocr(prep.for_ocr, version=args.version, model_type=args.model_type, engine=args.engine)
        texts[image] = result.text
        details[image] = {
            "crop_method": prep.crop_method, "preprocess_s": prep.seconds, "ocr_s": result.seconds,
            "mean_confidence": result.mean_confidence, "engine": result.engine,
            "quality_warnings": prep.quality.warnings,
        }
    return texts, details


def _lookup(texts: dict[str, object], image: str):
    for key in (image, Path(image).name, Path(image).stem):
        if key in texts:
            return texts[key]
    return None


def run_pipeline(truth: dict[str, dict], name: str, *, resume: bool = False) -> dict[str, dict]:
    """Run the full pipeline on each ground-truth image (warm model first).

    Predictions are saved after every receipt to eval/results/<name>.partial.json, so an
    interrupted run loses at most one receipt; ``resume`` skips receipts already in that file."""
    from app.keepawake import keep_awake
    from app.llm.client import warm_up
    from app.llm.prompts import EXTRACTION_SYSTEM
    from app.pipeline.run import process_image

    settings = get_settings()
    partial = settings.eval_results_dir / f"{name}.partial.json"
    partial.parent.mkdir(parents=True, exist_ok=True)
    predictions = json.loads(partial.read_text(encoding="utf-8")) if resume and partial.exists() else {}
    if predictions:
        print(f"  resuming: {len(predictions)} receipt(s) already done", file=sys.stderr, flush=True)

    with keep_awake():
        warm_up(settings.extract_model, EXTRACTION_SYSTEM)
        for n, image in enumerate(truth, 1):
            if image in predictions:
                continue
            started = datetime.now()
            try:
                predictions[image] = process_image(settings.samples_dir / image).to_dict()
            except Exception as error:  # a failure is a result too: score it as empty
                predictions[image] = {"items": [], "warnings": [{"code": "FAILED", "message": str(error)}],
                                      "status": "failed", "error": str(error)}
            p = predictions[image]
            seconds = (datetime.now() - started).total_seconds()
            print(f"  [{n}/{len(truth)}] {image}: {p.get('status')} in {seconds:.0f}s"
                  f"{' (VLM used)' if p.get('source') == 'vlm' else ' (VLM checked)' if p.get('ocr_text_vlm') else ''}",
                  file=sys.stderr, flush=True)
            partial.write_text(json.dumps(predictions, ensure_ascii=False), encoding="utf-8")
    return predictions


def save_report(kind: str, name: str, report: dict) -> Path:
    out_dir = get_settings().eval_results_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}_{kind}_{name}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def eval_ocr(texts: dict[str, str], name: str, truth: dict[str, dict]) -> dict:
    per_receipt = {}
    for image, gt in truth.items():
        predicted = _lookup(texts, image)
        if predicted is None or gt["text"] is None:
            continue
        per_receipt[image] = score_ocr(predicted, gt["text"], gt.get("key_values", []))
    return {"kind": "ocr", "name": name, "created": datetime.now().isoformat(timespec="seconds"),
            "summary": summarize_ocr(per_receipt), "receipts": per_receipt}


def eval_extraction(predictions: dict[str, dict], name: str, truth: dict[str, dict]) -> dict:
    per_receipt, timings = {}, {}
    for image, gt in truth.items():
        predicted = _lookup(predictions, image)
        if predicted is None:
            continue
        per_receipt[image] = score_extraction(predicted, gt)
        if predicted.get("timings"):
            timings[image] = predicted["timings"]
    summary = summarize_extraction(per_receipt)
    totals = [t.get("total_s") for t in timings.values() if t.get("total_s") is not None]
    if totals:
        summary["seconds_per_receipt_median"] = round(sorted(totals)[len(totals) // 2], 1)
        summary["seconds_per_receipt_max"] = round(max(totals), 1)
    return {"kind": "extraction", "name": name, "created": datetime.now().isoformat(timespec="seconds"),
            "summary": summary, "receipts": per_receipt, "timings": timings}


def print_report(report: dict) -> None:
    print(f"\n=== {report['kind'].upper()} — {report['name']} ===")
    for key, value in report["summary"].items():
        print(f"  {key:28s} {value}")
    for set_name, summary in report.get("summary_by_set", {}).items():
        print(f"  [{set_name}] key fields {summary['key_field_accuracy']}, all fields {summary['all_field_accuracy']}, "
              f"item F1 {summary['item_f1']}, categories {summary['category_accuracy']}, "
              f"wrong totals unflagged {summary['wrong_totals_unflagged']}")
    for image, result in report["receipts"].items():
        if report["kind"] == "ocr":
            print(f"  {image}: CER {result['cer']:.1%}, words {result['token_recall']:.0%}, "
                  f"keys {result['key_values_found']}/{result['key_values_total']}"
                  + (f", missed {result['key_values_missed']}" if result["key_values_missed"] else ""))
        else:
            wrong = [f for f, v in result["fields"].items() if v["status"] == "wrong"]
            items = result["items"]
            print(f"  {image}: items {items['matched']}/{items['expected']} matched "
                  f"({items['predicted']} predicted), wrong fields: {wrong or 'none'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="kind", required=True)

    ocr = sub.add_parser("ocr", help="score OCR text")
    ocr.add_argument("--name", required=True)
    src = ocr.add_mutually_exclusive_group(required=True)
    src.add_argument("--legacy-file", type=Path)
    src.add_argument("--text-dir", type=Path)
    src.add_argument("--rapid", action="store_true", help="run preprocessing + RapidOCR now")
    ocr.add_argument("--ocr-on-crop", action="store_true", help="give RapidOCR the cropped receipt")
    ocr.add_argument("--shadows", action="store_true", help="apply shadow removal")
    ocr.add_argument("--contrast", action="store_true", help="apply contrast stretch")
    ocr.add_argument("--version")
    ocr.add_argument("--model-type")
    ocr.add_argument("--engine")

    ext = sub.add_parser("extraction", help="score extracted receipt data")
    ext.add_argument("--name", required=True)
    src = ext.add_mutually_exclusive_group(required=True)
    src.add_argument("--predictions", type=Path)
    src.add_argument("--pipeline", action="store_true", help="run the full pipeline now (needs Ollama)")
    ext.add_argument("--resume", action="store_true", help="with --pipeline: continue an interrupted run of --name")
    for p in (ocr, ext):
        p.add_argument("--set", action="append", dest="sets",
                       help="only these ground-truth sets (tuning, dev, test); repeatable")

    args = parser.parse_args(argv)
    truth = load_ground_truth()
    if args.sets:
        truth = {k: v for k, v in truth.items() if v.get("set") in args.sets}
    if not truth:
        print("No ground truth found.", file=sys.stderr)
        return 1

    if args.kind == "ocr":
        details = {}
        if args.rapid:
            texts, details = run_rapid(truth, args)
        elif args.legacy_file:
            texts = read_legacy_ocr(args.legacy_file)
        else:
            texts = read_text_dir(args.text_dir)
        report = eval_ocr(texts, args.name, truth)
        if details:
            for image, info in details.items():
                report["receipts"][image].update(info)
            n = len(details)
            report["summary"]["seconds_per_receipt"] = round(
                sum(d["preprocess_s"] + d["ocr_s"] for d in details.values()) / n, 2)
            report["summary"]["mean_confidence"] = round(sum(d["mean_confidence"] for d in details.values()) / n, 4)
        report["texts"] = texts
    else:
        if args.pipeline:
            predictions = run_pipeline(truth, args.name, resume=args.resume)
        else:
            predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        report = eval_extraction(predictions, args.name, truth)
        report["predictions"] = predictions
        by_set = {}
        for image, gt in truth.items():
            if image in report["receipts"]:
                by_set.setdefault(gt.get("set", "?"), {})[image] = report["receipts"][image]
        if len(by_set) > 1:
            report["summary_by_set"] = {s: summarize_extraction(r) for s, r in by_set.items()}

    print_report(report)
    print(f"\nReport saved: {save_report(args.kind, args.name, report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
