"""Render the product demo video from the live TXN-INT-0002 investigation."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
BG = (5, 16, 27)
BG_LEFT = (10, 33, 46)
CARD = (12, 28, 42)
CARD_ALT = (16, 36, 52)
WHITE = (236, 242, 248)
MUTED = (148, 166, 182)
DIM = (92, 112, 128)
TEAL = (92, 214, 201)
TEAL_DEEP = (36, 150, 142)
BLUE = (86, 168, 232)
ORANGE = (232, 156, 86)
GREEN = (92, 214, 140)
AMBER = (214, 164, 88)
PILL_BG = (18, 48, 58)
PROGRESS = (58, 132, 214)

SANS = "/System/Library/Fonts/HelveticaNeue.ttc"
MONO = "/System/Library/Fonts/SFNSMono.ttf"


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        return ImageFont.truetype(MONO, size)
    return ImageFont.truetype(SANS, size, index=1 if bold else 0)


def new_canvas() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(BG_LEFT[0] * (1 - t) + BG[0] * t)
        g = int(BG_LEFT[1] * (1 - t) + BG[1] * t)
        b = int(BG_LEFT[2] * (1 - t) + BG[2] * t)
        draw.line([(0, y), (420, y)], fill=(r, g, b))
    return img


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    fill,
    fg=BG,
    size: int = 18,
    pad_x: int = 16,
    pad_y: int = 8,
) -> int:
    f = font(size, bold=True)
    tw, th = draw.textbbox((0, 0), text, font=f)[2:]
    x, y = xy
    box = (x, y, x + tw + pad_x * 2, y + th + pad_y * 2)
    rounded(draw, box, 18, fill)
    draw.text((x + pad_x, y + pad_y - 1), text, font=f, fill=fg)
    return box[2]


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=f) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def header(draw: ImageDraw.ImageDraw, *, badge: str = "SYNTHETIC DEMO") -> None:
    draw.text((56, 36), "FINANCIAL TRANSACTION RESOLUTION", font=font(16, bold=True), fill=DIM)
    pill(draw, (1360, 28), badge, fill=TEAL, fg=BG, size=15)


def footer(draw: ImageDraw.ImageDraw, step: str, progress: float) -> None:
    draw.text((56, 838), step, font=font(18), fill=MUTED)
    bar_y = 872
    rounded(draw, (420, bar_y, 1544, bar_y + 6), 3, (20, 36, 48))
    filled = 420 + int(1124 * max(0.04, min(progress, 1.0)))
    rounded(draw, (420, bar_y, filled, bar_y + 6), 3, PROGRESS)


def title_block(draw: ImageDraw.ImageDraw, title: str, subtitle: str, y: int = 108) -> int:
    tf = font(42, bold=True)
    sf = font(22)
    draw.text((56, y), title, font=tf, fill=WHITE)
    for i, line in enumerate(wrap(draw, subtitle, sf, 1400)):
        draw.text((56, y + 64 + i * 32), line, font=sf, fill=MUTED)
    return y + 64 + 32 * len(wrap(draw, subtitle, sf, 1400)) + 28


def check_circle(draw: ImageDraw.ImageDraw, cx: int, cy: int, done: bool) -> None:
    r = 14
    if done:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GREEN)
        draw.line([(cx - 6, cy + 1), (cx - 1, cy + 6), (cx + 7, cy - 5)], fill=BG, width=3)
    else:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=DIM, width=2)


def slide_title() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    d.text((56, 170), "From customer prompt to back-office review", font=font(46, bold=True), fill=WHITE)
    sub = (
        "This cut follows the live Cursor investigation of TXN-INT-0002 on ACCT-0133: "
        "policy 1.2, deterministic evidence, Gemini synthesis, merchant-contact confirmation, then a PENDING_REVIEW case."
    )
    y = 250
    for line in wrap(d, sub, font(22), 1420):
        d.text((56, y), line, font=font(22), fill=MUTED)
        y += 34

    chips = [
        ("POLICY", CARD_ALT, MUTED),
        ("EVIDENCE", CARD_ALT, MUTED),
        ("SYNTHESIS", CARD_ALT, MUTED),
        ("CONFIRM", TEAL, BG),
        ("CASE", TEAL, BG),
        ("REVIEW", TEAL, BG),
    ]
    x = 56
    for label, fill, fg in chips:
        x = pill(d, (x, 430), label, fill=fill, fg=fg, size=18) + 16

    d.text((56, 780), "Updated from the live MCP workflow  ·  TXN-INT-0002  ·  ACCT-0133", font=font(18), fill=DIM)
    footer(d, "Live investigation", 0.08)
    return img


def slide_prompt() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    title_block(
        d,
        "One prompt starts the investigation",
        "The host asked for the concern, mapped “unrecognized” to the live policy, and reused one request_id.",
    )
    rounded(d, (56, 280, 1544, 760), 22, CARD)
    d.ellipse((88, 316, 128, 356), fill=BLUE)
    d.text((100, 322), "U", font=font(20, bold=True), fill=BG)
    d.text((148, 318), "Investigate TXN-INT-0002 on Acct-0133", font=font(24, bold=True), fill=WHITE)
    d.text((148, 358), "Customer concern: 1 · I do not recognize this charge", font=font(20), fill=MUTED)

    pill(d, (148, 416), "investigate_transaction", fill=ORANGE, fg=BG, size=16)
    note = (
        "The host read policy://disputes/unrecognized-transaction (version 1.2) and kept every "
        "tool call on the same correlation id."
    )
    y = 478
    for line in wrap(d, note, font(20), 1280):
        d.text((148, y), line, font=font(20), fill=MUTED)
        y += 30

    d.text((148, 620), "request_id", font=font(16, bold=True), fill=GREEN)
    d.text((148, 650), "inv-20260829-acct-0133-txn-int-0002", font=font(22, mono=True), fill=TEAL)
    d.text((148, 700), "policy  POL-DSP-UNREC-001  ·  version 1.2", font=font(18, mono=True), fill=DIM)
    footer(d, "1 · Customer prompt", 0.18)
    return img


def slide_tools(complete: int) -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    title_block(
        d,
        "The server gathers account-scoped evidence",
        "Read-only tools · one correlated request · no cross-account leakage",
    )
    rows = [
        ("get_account_summary", "Active consumer credit card · •••• 1771 · GA"),
        ("get_transaction_details", "$21.35 · Lumen Streaming · posted 2026-04-05"),
        ("resolve_merchant", "LUMENSTREAMING -> Lumen Streaming · HIGH"),
        ("check_duplicate_charge", "HIGH · likely duplicate of TXN-INT-0001"),
        ("get_transaction_details", "Paired charge TXN-INT-0001 · same $21.35 same day"),
        ("get_audit_trace", "Sanitized trail · 5 events · no PII"),
    ]
    y = 286
    for i, (name, result) in enumerate(rows):
        done = i < complete
        check_circle(d, 86, y + 18, done)
        d.text((120, y), name, font=font(22, mono=True), fill=WHITE if done else DIM)
        d.text((720, y), result if done else "waiting…", font=font(20), fill=MUTED if done else DIM)
        y += 72
    footer(d, "2 · Tool orchestration", 0.18 + 0.04 * complete)
    return img


def slide_evidence() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    title_block(
        d,
        "A high-confidence duplicate emerges",
        "Evidence analysis is deterministic. Gemini is not used for this step.",
    )
    rounded(d, (56, 286, 772, 760), 22, CARD)
    pill(d, (84, 314), "TRANSACTION", fill=BLUE, fg=BG, size=15)
    d.text((84, 372), "TXN-INT-0002", font=font(28, mono=True), fill=WHITE)
    d.text((84, 430), "$21.35 USD", font=font(48, bold=True), fill=WHITE)
    d.text((84, 508), "Lumen Streaming", font=font(26, bold=True), fill=GREEN)
    d.text((84, 556), "April 4, 2026 · posted April 5", font=font(20), fill=MUTED)
    d.text((84, 680), "prefix_match  ·  0.92  ·  HIGH", font=font(18, mono=True), fill=GREEN)

    rounded(d, (828, 286, 1544, 760), 22, CARD)
    pill(d, (856, 314), "DUPLICATE CHECK", fill=ORANGE, fg=BG, size=15)
    d.text((856, 372), "HIGH confidence", font=font(32, bold=True), fill=GREEN)
    d.text((856, 430), "Candidate TXN-INT-0001", font=font(24, mono=True), fill=WHITE)
    reason = "Identical amount 21.35 USD at Lumen Streaming on the same transaction date. Both charges used the same capture channel."
    y = 490
    for line in wrap(d, reason, font(20), 620):
        d.text((856, y), line, font=font(20), fill=MUTED)
        y += 30
    pill(d, (856, 680), "duplicate_likely: true", fill=(18, 64, 42), fg=GREEN, size=16)
    footer(d, "3 · Deterministic evidence", 0.46)
    return img


def slide_synthesis() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    title_block(d, "Gemini turns evidence into a careful reply", "")
    pill(d, (56, 176), "gemini-2.5-flash", fill=PILL_BG, fg=TEAL, size=15)
    pill(d, (290, 176), "POL-DSP-UNREC-001", fill=PILL_BG, fg=MUTED, size=15)

    rounded(d, (56, 240, 1544, 760), 22, CARD)
    reply = (
        "TXN-INT-0002 is a posted $21.35 charge at Lumen Streaming, a digital subscription. "
        "TXN-INT-0001 is highly likely to be a duplicate: same amount, merchant, date, and capture channel."
    )
    y = 276
    for line in wrap(d, reply, font(24), 1400):
        d.text((92, y), line, font=font(24), fill=WHITE)
        y += 38

    d.text((92, 470), "NEXT STEP", font=font(16, bold=True), fill=AMBER)
    next_step = (
        "Because duplicate_likely is true, policy 1.2 requires asking whether the customer already "
        "contacted Lumen Streaming about the duplicate. Do not open a case until they say yes."
    )
    y = 510
    for line in wrap(d, next_step, font(22), 1400):
        d.text((92, y), line, font=font(22), fill=MUTED)
        y += 34
    footer(d, "4 · Gemini synthesis", 0.58)
    return img


def slide_confirm() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    title_block(d, "The customer must confirm merchant contact.", "")
    pill(d, (56, 176), "POLICY 1.2 GATE", fill=AMBER, fg=BG, size=15)
    d.text((250, 180), "A model cannot skip this by sending approved=true.", font=font(20), fill=MUTED)

    rounded(d, (56, 250, 1544, 760), 22, CARD)
    d.ellipse((88, 286, 128, 326), fill=BLUE)
    d.text((100, 292), "U", font=font(20, bold=True), fill=BG)
    d.text((148, 286), "Have you already contacted Lumen Streaming about this duplicate?", font=font(22), fill=MUTED)
    d.text((148, 332), "yes", font=font(36, bold=True), fill=WHITE)

    pill(d, (148, 410), "confirm_unrecognized_transaction", fill=ORANGE, fg=BG, size=16)
    d.text(
        (148, 472),
        "The host presents the server-issued confirmation_token. It does not invent one.",
        font=font(20),
        fill=MUTED,
    )

    rows = [
        ("investigation_id", "inv-20260829-acct-0133-txn-int-0002"),
        ("confirmation_token", "cnf_uQYI…Nwo8"),
        ("idempotency_key", "idem-20260829-acct-0133-txn-int-0002"),
    ]
    y = 530
    for key, value in rows:
        d.text((148, y), key, font=font(18, mono=True), fill=DIM)
        d.text((460, y), value, font=font(18, mono=True), fill=TEAL)
        y += 42
    footer(d, "5 · Customer confirmation", 0.70)
    return img


def slide_case() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    title_block(d, "Confirmation writes the case immediately", "")
    pill(d, (56, 176), "PENDING_REVIEW", fill=ORANGE, fg=BG, size=15)
    d.text(
        (290, 180),
        "The row exists before a reviewer ever opens the app. Nothing is submitted to an issuer.",
        font=font(20),
        fill=MUTED,
    )

    rows = [
        ("Case", "DSP-D8CF82D7"),
        ("Status", "pending_review"),
        ("Transaction", "TXN-INT-0002"),
        ("Reason code", "NEEDS_SPECIALIST_REVIEW"),
        ("Review path", "/reviews/DSP-D8CF82D7"),
        ("Evidence hash", "f1470bedf799…bfa8fd64"),
        ("Customer message", "We will investigate the case and get back in 10 business days."),
    ]
    y = 250
    for label, value in rows:
        d.text((72, y), label, font=font(22), fill=MUTED)
        d.text((420, y), value, font=font(22, mono=label != "Customer message"), fill=WHITE)
        y += 68
    footer(d, "6 · Persisted case", 0.80)
    return img


def slide_review() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    title_block(
        d,
        "Back-office review is a separate app",
        "Not an MCP tool. An authenticated reviewer opens the existing case and records APPROVE or REJECT.",
    )
    rounded(d, (56, 286, 1544, 760), 22, CARD)
    d.text((92, 330), "GET /reviews/DSP-D8CF82D7", font=font(30, mono=True), fill=GREEN)
    note = (
        "Identity comes from a verified JWT (sub + dispute:review). The JSON body cannot supply reviewer_id. "
        "This investigation stopped after case creation — the case remains PENDING_REVIEW until a human decides."
    )
    y = 410
    for line in wrap(d, note, font(22), 1360):
        d.text((92, y), line, font=font(22), fill=MUTED)
        y += 34
    d.text(
        (92, 620),
        "approved=true is not accepted and is not proof of confirmation.",
        font=font(20, bold=True),
        fill=AMBER,
    )
    footer(d, "7 · Human-in-the-loop review", 0.90)
    return img


def slide_close() -> Image.Image:
    img = new_canvas()
    d = ImageDraw.Draw(img)
    header(d)
    d.text((56, 140), "Evidence first. Human control before issuer claims.", font=font(40, bold=True), fill=WHITE)
    d.text(
        (56, 210),
        "The case is synthetic. Review decides an internal file; it does not file a network dispute.",
        font=font(22),
        fill=MUTED,
    )

    cards = [
        ("ACCOUNT-SCOPED", BLUE, "Every evidence query is constrained to one account."),
        ("POLICY-GROUNDED", GREEN, "The server loads trusted policy resources itself."),
        ("AUDITABLE", ORANGE, "One request_id connects tools, synthesis, confirmation, and review."),
        ("HUMAN-GATED", TEAL, "Merchant-contact yes writes the case. Reviewers decide that same case."),
    ]
    x = 56
    for label, color, body in cards:
        rounded(d, (x, 320, x + 360, 620), 20, CARD)
        pill(d, (x + 24, 348), label, fill=color, fg=BG, size=14)
        y = 430
        for line in wrap(d, body, font(20), 300):
            d.text((x + 24, y), line, font=font(20), fill=WHITE)
            y += 30
        x += 384

    d.text(
        (56, 780),
        "All accounts, transactions, policies, and case records shown are synthetic.",
        font=font(18),
        fill=DIM,
    )
    footer(d, "Safety and auditability by design", 1.0)
    return img


def write_still(path: Path, image: Image.Image) -> None:
    image.save(path, "PNG")


def render(output: Path, ffmpeg: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="demo-render-") as tmp:
        tmp_path = Path(tmp)
        scenes: list[tuple[str, Image.Image, float]] = [
            ("00_title", slide_title(), 5.0),
            ("01_prompt", slide_prompt(), 6.5),
        ]
        for i in range(1, 7):
            scenes.append((f"02_tools_{i}", slide_tools(i), 1.25))
        scenes.extend(
            [
                ("03_evidence", slide_evidence(), 6.5),
                ("04_synthesis", slide_synthesis(), 7.0),
                ("05_confirm", slide_confirm(), 7.0),
                ("06_case", slide_case(), 6.5),
                ("07_review", slide_review(), 6.5),
                ("08_close", slide_close(), 6.5),
            ]
        )

        concat_lines = []
        for name, image, duration in scenes:
            frame = tmp_path / f"{name}.png"
            write_still(frame, image)
            concat_lines.append(f"file '{frame}'")
            concat_lines.append(f"duration {duration:.2f}")
        concat_lines.append(f"file '{tmp_path / (scenes[-1][0] + '.png')}'")
        concat_file = tmp_path / "concat.txt"
        concat_file.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-vf",
            "fps=24,format=yuv420p",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
            str(output),
        ]
        subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("financial-transaction-resolution-demo.mp4"),
    )
    parser.add_argument("--ffmpeg", default=os.environ.get("FFMPEG", "ffmpeg"))
    args = parser.parse_args()
    render(args.output, args.ffmpeg)


if __name__ == "__main__":
    main()
