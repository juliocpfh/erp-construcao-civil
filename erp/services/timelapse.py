"""Time-lapse da obra em .mp4 via OpenCV (com transcodificação H.264 via ffmpeg quando disponível)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date

import cv2
import numpy as np


@dataclass
class Frame:
    day: date
    caption: str
    image: bytes


def _decode(data: bytes, size: tuple[int, int]) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    w, h = size
    ih, iw = img.shape[:2]
    scale = min(w / iw, h / ih)
    resized = cv2.resize(img, (int(iw * scale), int(ih * scale)), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    y0, x0 = (h - resized.shape[0]) // 2, (w - resized.shape[1]) // 2
    canvas[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized
    return canvas


def _overlay(img: np.ndarray, title: str, frame: Frame, idx: int, total: int) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    cv2.rectangle(out, (0, h - 46), (w, h), (20, 20, 20), -1)
    cv2.putText(out, f"{frame.day:%d/%m/%Y}  |  {frame.caption}"[:70], (12, h - 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.rectangle(out, (0, 0), (w, 30), (20, 20, 20), -1)
    cv2.putText(out, title[:60], (12, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 1, cv2.LINE_AA)
    bar = int(w * (idx + 1) / max(total, 1))
    cv2.rectangle(out, (0, h - 50), (bar, h - 46), (0, 170, 255), -1)
    return out


def _transcode_h264(src: str) -> bytes | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    dst = src.replace(".mp4", "_h264.mp4")
    try:
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", src, "-c:v", "libx264", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst],
                       check=True, timeout=120)
        with open(dst, "rb") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return None
    finally:
        if os.path.exists(dst):
            os.remove(dst)


def build_timelapse(frames: list[Frame], title: str = "Time-lapse da Obra", fps: int = 12,
                    seconds_per_photo: float = 0.6, size: tuple[int, int] = (960, 540),
                    transition_frames: int = 4) -> bytes:
    """Gera o vídeo .mp4 em memória (bytes). Lança ValueError se não houver fotos válidas."""
    frames = sorted(frames, key=lambda f: f.day)
    decoded = [(f, _decode(f.image, size)) for f in frames]
    decoded = [(f, img) for f, img in decoded if img is not None]
    if not decoded:
        raise ValueError("Nenhuma foto válida para gerar o vídeo.")
    hold = max(int(fps * seconds_per_photo), 1)
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        if not writer.isOpened():
            raise RuntimeError("OpenCV não conseguiu abrir o codificador de vídeo.")
        prev = None
        total = len(decoded)
        for i, (frame, img) in enumerate(decoded):
            composed = _overlay(img, title, frame, i, total)
            if prev is not None:
                for k in range(1, transition_frames + 1):  # transição em fade
                    alpha = k / (transition_frames + 1)
                    writer.write(cv2.addWeighted(prev, 1 - alpha, composed, alpha, 0))
            for _ in range(hold):
                writer.write(composed)
            prev = composed
        writer.release()
        h264 = _transcode_h264(path)
        if h264:
            return h264
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        if os.path.exists(path):
            os.remove(path)
