#!/usr/bin/env python3
import argparse
import json
import mimetypes
import struct
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zlib
from pathlib import Path


DEFAULT_BASE_URL = "http://192.168.1.41:8189"
BOUNDARY = "----OpenClawInpaintBoundary7MA4YWxkTrZu0gW"


def read_image_size(path: Path) -> tuple[int, int]:
    """Read width/height from PNG or JPEG using stdlib only."""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        # IHDR is at offset 8 (length+tag), width/height at offsets 16/20
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height
    if data[:2] == b"\xff\xd8":
        i = 2
        n = len(data)
        while i < n - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            # Standalone markers (no length)
            if marker in (0xD8, 0xD9) or (0xD0 <= marker <= 0xD7):
                i += 2
                continue
            # SOF markers (excluding DHT=C4, JPG=C8, DAC=CC)
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height = int.from_bytes(data[i + 5:i + 7], "big")
                width = int.from_bytes(data[i + 7:i + 9], "big")
                return width, height
            length = int.from_bytes(data[i + 2:i + 4], "big")
            i += 2 + length
    raise ValueError(f"Unsupported image format (need PNG or JPEG): {path}")


def make_mask_png(width: int, height: int, rects, invert: bool = False) -> bytes:
    """Build a grayscale PNG mask. White = inpaint area, black = keep (FLUX Fill convention)."""
    fg = 0 if invert else 255
    bg = 255 if invert else 0

    rows = [bytearray([bg]) * width for _ in range(height)]
    fill = bytes([fg])
    for (rx, ry, rw, rh) in rects:
        x0 = max(0, rx)
        y0 = max(0, ry)
        x1 = min(width, rx + rw)
        y1 = min(height, ry + rh)
        if x1 <= x0 or y1 <= y0:
            continue
        run = fill * (x1 - x0)
        for y in range(y0, y1):
            rows[y][x0:x1] = run

    raster = bytearray()
    for r in rows:
        raster.append(0)  # PNG filter type 0 (None)
        raster.extend(r)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # 8-bit grayscale
    idat = zlib.compress(bytes(raster), 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def parse_rect(s: str) -> tuple[int, int, int, int]:
    parts = s.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"--mask-rect expects x,y,w,h, got {s!r}")
    try:
        x, y, w, h = (int(p.strip()) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--mask-rect values must be integers: {s!r}")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f"--mask-rect width/height must be positive: {s!r}")
    return (x, y, w, h)


def parse_size(s: str) -> tuple[int, int]:
    parts = s.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"--mask-size expects W,H, got {s!r}")
    try:
        w, h = (int(p.strip()) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--mask-size values must be integers: {s!r}")
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f"--mask-size must be positive: {s!r}")
    return (w, h)


def http_json(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_json(url: str, payload: dict, timeout: float = 60.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_multipart_image(url: str, image_path: Path, timeout: float = 120.0):
    mime = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    body = b"".join([
        f"--{BOUNDARY}\r\n".encode(),
        f"Content-Disposition: form-data; name=\"image\"; filename=\"{image_path.name}\"\r\n".encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        image_path.read_bytes(),
        f"\r\n--{BOUNDARY}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download_file(url: str, out_path: Path, timeout: float = 120.0):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r, out_path.open("wb") as f:
        f.write(r.read())


def log_json(prefix: str, payload: dict):
    print(f"{prefix}: {json.dumps(payload, ensure_ascii=False)}", flush=True)


def main():
    p = argparse.ArgumentParser(
        description="Submit and wait for an Images API inpainting job (FLUX Fill). "
                    "Mask can be a file (--mask) or generated inline from --mask-rect."
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--input", required=True, help="Path to source image")
    p.add_argument("--mask", help="Path to mask image (white = inpaint area, black = keep)")
    p.add_argument("--mask-rect", action="append", type=parse_rect, default=[],
                   help="Generate mask from rectangle x,y,w,h (white area on black background). "
                        "Repeatable to combine multiple rectangles. Mutually exclusive with --mask.")
    p.add_argument("--mask-size", type=parse_size,
                   help="Mask dimensions W,H when using --mask-rect. Defaults to source image size.")
    p.add_argument("--mask-invert", action="store_true",
                   help="Invert generated mask (rectangles become black, background white).")
    p.add_argument("--prompt", required=True, help="What to generate in the masked area")
    p.add_argument("--denoise", type=float, default=1.0, help="Denoise strength (0.8-1.0 for full replace, 0.5-0.7 for correction)")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--guidance-scale", type=float, default=3.5)
    p.add_argument("--seed", type=int, default=-1)
    p.add_argument("--output", required=True)
    p.add_argument("--poll-seconds", type=float, default=5.0)
    p.add_argument("--timeout-seconds", type=float, default=700.0)
    args = p.parse_args()

    input_path = Path(args.input)
    if not input_path.exists() or not input_path.is_file():
        print(f"Input image not found: {input_path}", file=sys.stderr)
        return 2

    if args.mask and args.mask_rect:
        print("--mask and --mask-rect are mutually exclusive", file=sys.stderr)
        return 2
    if not args.mask and not args.mask_rect:
        print("must provide either --mask or --mask-rect", file=sys.stderr)
        return 2

    tmp_mask: Path | None = None
    if args.mask:
        mask_path = Path(args.mask)
        if not mask_path.exists() or not mask_path.is_file():
            print(f"Mask image not found: {mask_path}", file=sys.stderr)
            return 2
    else:
        if args.mask_size:
            mw, mh = args.mask_size
        else:
            try:
                mw, mh = read_image_size(input_path)
            except Exception as e:
                print(f"Could not auto-detect mask size from {input_path}: {e}. "
                      f"Specify --mask-size W,H explicitly.", file=sys.stderr)
                return 2
        png_bytes = make_mask_png(mw, mh, args.mask_rect, invert=args.mask_invert)
        tmp = tempfile.NamedTemporaryFile(prefix="openclaw_mask_", suffix=".png", delete=False)
        tmp.write(png_bytes)
        tmp.close()
        tmp_mask = Path(tmp.name)
        mask_path = tmp_mask
        log_json("generated_mask", {"path": str(tmp_mask), "width": mw, "height": mh,
                                    "rects": args.mask_rect, "invert": args.mask_invert})

    try:
        return run_inpaint(args, input_path, mask_path)
    finally:
        if tmp_mask is not None:
            try:
                tmp_mask.unlink()
            except OSError:
                pass


def run_inpaint(args, input_path: Path, mask_path: Path) -> int:
    # Upload source image
    try:
        upload_img = http_post_multipart_image(f"{args.base_url}/upload", input_path, timeout=120)
        log_json("upload_image", upload_img)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Image upload failed: HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Image upload failed: {e}", file=sys.stderr)
        return 1

    # Upload mask image
    try:
        upload_mask = http_post_multipart_image(f"{args.base_url}/upload", mask_path, timeout=120)
        log_json("upload_mask", upload_mask)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Mask upload failed: HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Mask upload failed: {e}", file=sys.stderr)
        return 1

    payload = {
        "prompt": args.prompt,
        "model": "flux-fill",
        "input_image": upload_img["filename"],
        "mask_image": upload_mask["filename"],
        "denoise": args.denoise,
        "steps": args.steps,
        "guidance_scale": args.guidance_scale,
        "seed": args.seed,
    }

    try:
        job = http_post_json(f"{args.base_url}/jobs", payload, timeout=60)
        log_json("job", job)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Job submission failed: HTTP {e.code}: {body}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Job submission failed: {e}", file=sys.stderr)
        return 1

    job_id = job["job_id"]
    deadline = time.time() + args.timeout_seconds

    while time.time() < deadline:
        try:
            state = http_json(f"{args.base_url}/jobs/{job_id}", timeout=30)
            log_json("state", state)
        except Exception as e:
            print(f"Failed to poll job {job_id}: {e}", file=sys.stderr)
            time.sleep(args.poll_seconds)
            continue

        current = state.get("status")
        if current == "completed":
            out_path = Path(args.output)
            try:
                download_file(f"{args.base_url}/jobs/{job_id}/result", out_path, timeout=120)
            except Exception as e:
                print(f"Failed to download result for job {job_id}: {e}", file=sys.stderr)
                return 1
            if not out_path.exists() or out_path.stat().st_size == 0:
                print("Downloaded file is empty", file=sys.stderr)
                return 1
            print(str(out_path), flush=True)
            return 0

        if current in {"failed", "cancelled"}:
            print(json.dumps(state, ensure_ascii=False), file=sys.stderr)
            return 1

        time.sleep(args.poll_seconds)

    print(f"Timed out waiting for inpaint job {job_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
