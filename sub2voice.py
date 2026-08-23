#!/usr/bin/env python3
"""
sub2voice — Tự động chuyển phụ đề burned-in (chữ trên màn hình) của video
thành voiceover tiếng Việt.

Quy trình:
  1. Extract frame dày (mặc định 3 fps) từ video.
  2. Crop vùng phụ đề (cuối frame), phóng to để dễ OCR.
  3. Lọc bỏ frame trùng (cùng 1 câu) -> chỉ giữ frame đại diện mỗi câu.
  4. Dùng Vision (OpenAI-compatible) đọc text tiếng Việt từ từng frame.
  5. TTS (edge-tts, giọng Nam Minh) từng câu, lồng vào đúng timeline.
  6. Ghép audio VN vào video, mute tiếng gốc.

Cài đặt:
  pip install pillow edge-tts flask

Chạy CLI:
  python3 sub2voice.py video.mp4 --out video_vi.mp4
  python3 sub2voice.py video.mp4 --voice vi-VN-HoaiMyNeural --rate +10%

Chạy Web UI:
  python3 app.py            # mở http://localhost:5000

Biến môi trường:
  VISION_API_KEY, VISION_BASE_URL, VISION_MODEL   (mặc định dùng OpenAI)
"""
import argparse, os, sys, json, time, subprocess, tempfile
from PIL import Image, ImageChops

# ---------- CẤU HÌNH VISION ----------
# Hỗ trợ OpenAI-compatible: OpenAI, OpenRouter (free), hoặc local (ollama/llama.cpp)
VISION_API_KEY = os.environ.get("VISION_API_KEY", "")
VISION_BASE_URL = os.environ.get("VISION_BASE_URL", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "")
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "openai").lower()

if not VISION_BASE_URL:
    if VISION_PROVIDER == "openrouter":
        VISION_BASE_URL = "https://openrouter.ai/api/v1"
        VISION_MODEL = VISION_MODEL or "google/gemini-flash-1.5"
    else:  # openai
        VISION_BASE_URL = "https://api.openai.com/v1"
        VISION_MODEL = VISION_MODEL or "gpt-4o-mini"
# Nếu dùng local (ollama/llama.cpp): set VISION_BASE_URL + VISION_MODEL tương ứng.

def vision_read_text(image_path):
    """Gọi Vision API đọc text tiếng Việt từ crop phụ đề. Trả về str hoặc ''. """
    if not VISION_API_KEY:
        raise RuntimeError("Thiếu VISION_API_KEY. Set env hoặc dùng --offline.")
    import base64, requests
    b64 = base64.b64encode(open(image_path, "rb").read()).decode()
    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Đây là vùng phụ đề dưới cùng video (đã phóng to). "
                                          "Đọc nguyên văn dòng chữ tiếng Việt. Chỉ trả lời nội dung chữ, không giải thích."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]
        }],
        "max_tokens": 200,
    }
    headers = {"Authorization": f"Bearer {VISION_API_KEY}", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            r = requests.post(f"{VISION_BASE_URL}/chat/completions", headers=headers,
                              json=payload, timeout=60)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"  vision retry {attempt+1}: {e}")
            time.sleep(3)
    return ""

# ---------- TRÍCH FRAME + LỌC TRÙNG ----------
def extract_frames(video, fps, workdir):
    d = os.path.join(workdir, "dense")
    os.makedirs(d, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", video, "-vf", f"fps={fps}",
                    "-q:v", "4", os.path.join(d, "f_%05d.jpg")],
                   check=True, capture_output=True)
    return sorted([os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jpg")])

def sub_band(img, top=0.80, bot=0.97, scale=3):
    w, h = img.size
    band = img.crop((0, int(h*top), w, int(h*bot)))
    return band.resize((band.size[0]*scale, band.size[1]*scale))

def dedup_frames(frames, fps, min_gap=1.0, diff_thresh=6.0):
    """Trả về list (time_sec, frame_path) chỉ giữ frame có phụ đề đổi."""
    reps = []
    prev = None
    prev_t = -10
    for fp in frames:
        idx = int(os.path.basename(fp).split("_")[1].split(".")[0])
        t = idx / fps
        band = sub_band(Image.open(fp).convert("L"))
        keep = False
        if prev is None:
            keep = True
        else:
            diff = ImageChops.difference(band, prev)
            stat = sum(diff.getdata()) / (band.size[0]*band.size[1])
            if stat > diff_thresh and (t - prev_t) >= min_gap:
                keep = True
        if keep:
            reps.append((t, fp))
            prev = band
            prev_t = t
    return reps

# ---------- TTS ----------
def tts(text, voice, rate, out_mp3):
    import edge_tts, asyncio
    async def _run():
        comm = edge_tts.Communicate(text, voice, rate=rate)
        await comm.save(out_mp3)
    asyncio.run(_run())

# ---------- GHÉP AUDIO ----------
def build_audio(segs, total_dur, out_mp3, volume=2.2):
    """segs: list (start_sec, mp3_path). Mix vào 1 track, mute chỗ trống."""
    n = len(segs)
    if n == 0:
        raise RuntimeError("Không có câu nào để ghép.")
    inputs = ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={total_dur}"]
    fparts = []
    for i, (t, p) in enumerate(segs):
        inputs += ["-i", p]
        delay = int(t*1000)
        fparts.append(f"[{i+1}:a]adelay={delay}|{delay}[d{i}]")
    half = (n+1)//2
    g1 = "".join(f"[d{i}]" for i in range(half))
    g2 = "".join(f"[d{i}]" for i in range(half, n))
    fparts.append(f"{g1}amix=inputs={half}:duration=longest[m1]")
    fparts.append(f"{g2}amix=inputs={n-half}:duration=longest[m2]")
    fparts.append(f"[m1][m2]amix=inputs=2:duration=longest,volume={volume}[aout]")
    fc = ";".join(fparts)
    subprocess.run(["ffmpeg", "-y"] + inputs + ["-filter_complex", fc,
                   "-map", "[aout]", "-c:a", "libmp3lame", "-b:a", "160k", out_mp3],
                   check=True, capture_output=True)

def mux(video, audio, out):
    subprocess.run(["ffmpeg", "-y", "-i", video, "-i", audio,
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                    "-c:a", "copy", "-shortest", out],
                   check=True, capture_output=True)

# ---------- PIPELINE CHÍNH (có callback progress) ----------
def run_pipeline(video, out="output_vi.mp4", voice="vi-VN-NamMinhNeural",
                 rate="+12%", volume=2.2, fps=3.0, workdir=None,
                 progress_cb=None):
    """Chạy full pipeline. progress_cb(step, total_steps, msg) được gọi liên tục."""
    def prog(step, msg):
        if progress_cb:
            progress_cb(step, 5, msg)

    workdir = workdir or tempfile.mkdtemp(prefix="sub2voice_")
    os.makedirs(workdir, exist_ok=True)

    prog(1, f"Extract frames ({fps} fps)...")
    frames = extract_frames(video, fps, workdir)
    prog(1, f"Extract xong: {len(frames)} frames")

    prog(2, "Lọc frame trùng (chỉ giữ câu mới)...")
    reps = dedup_frames(frames, fps, min_gap=1.0/fps*3, diff_thresh=6.0)
    prog(2, f"Tìm được {len(reps)} câu đại diện")

    prog(3, "Đọc phụ đề bằng Vision...")
    segs_text = []
    for i, (t, fp) in enumerate(reps):
        txt = vision_read_text(fp)
        if txt and txt.lower() not in ("", "không có chữ", "không"):
            segs_text.append((t, txt))
            prog(3, f"[{i+1}/{len(reps)}] {t:.1f}s: {txt[:50]}")
        else:
            prog(3, f"[{i+1}/{len(reps)}] {t:.1f}s: (bỏ - không có chữ)")
    if not segs_text:
        raise RuntimeError("Không đọc được phụ đề nào.")
    prog(3, f"Đọc xong {len(segs_text)} câu")

    prog(4, "TTS tiếng Việt...")
    seg_dir = os.path.join(workdir, "segs")
    os.makedirs(seg_dir, exist_ok=True)
    segs_mp3 = []
    for i, (t, txt) in enumerate(segs_text):
        p = os.path.join(seg_dir, f"seg_{i:03d}.mp3")
        tts(txt, voice, rate, p)
        segs_mp3.append((t, p))
        prog(4, f"TTS {i+1}/{len(segs_text)}")
    prog(4, "TTS xong")

    dur = float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nw=1:nk=1",video],capture_output=True,text=True).stdout.strip())
    track = os.path.join(workdir, "vn_track.mp3")
    build_audio(segs_mp3, dur, track, volume)

    prog(5, "Ghép vào video...")
    mux(video, track, out)
    prog(5, f"XONG -> {out}")
    return out

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(description="Chuyển phụ đề trên màn hình -> voice VN")
    ap.add_argument("video")
    ap.add_argument("--out", default="output_vi.mp4")
    ap.add_argument("--voice", default="vi-VN-NamMinhNeural")
    ap.add_argument("--rate", default="+12%")
    ap.add_argument("--volume", type=float, default=2.2)
    ap.add_argument("--fps", type=float, default=3.0, help="số frame/giây extract")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    def cb(step, total, msg):
        print(f"[{step}/{total}] {msg}")
    run_pipeline(args.video, args.out, args.voice, args.rate,
                 args.volume, args.fps, args.workdir, cb)

if __name__ == "__main__":
    main()
