#!/usr/bin/env python3
"""Web UI cho sub2voice — kéo-thả video, theo dõi progress realtime, tải kết quả."""
import os, uuid, json, threading, queue
from flask import Flask, render_template_string, request, jsonify, send_file, Response
import sub2voice as sv

app = Flask(__name__)
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# mỗi job lưu 1 queue progress + kết quả
jobs = {}

INDEX = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sub2voice — Phụ đề màn hình → Voice VN</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, system-ui, sans-serif; background:#0f1115; color:#e8e8e8; margin:0; padding:24px; }
  .wrap { max-width:720px; margin:auto; }
  h1 { font-size:22px; margin-bottom:4px; }
  .sub { color:#8b98a5; font-size:13px; margin-bottom:20px; }
  .drop { border:2px dashed #3a4150; border-radius:12px; padding:40px; text-align:center; cursor:pointer; transition:.2s; }
  .drop.hover { border-color:#4f9cff; background:#161b26; }
  .drop small { color:#8b98a5; }
  .opts { display:flex; gap:12px; flex-wrap:wrap; margin:16px 0; }
  .opts label { font-size:13px; color:#b3bcc9; display:flex; flex-direction:column; gap:4px; }
  .opts select, .opts input { background:#161b26; border:1px solid #3a4150; color:#fff; padding:6px 8px; border-radius:6px; }
  button.go { background:#4f9cff; color:#fff; border:0; padding:10px 20px; border-radius:8px; font-size:15px; cursor:pointer; }
  button.go:disabled { opacity:.4; cursor:not-allowed; }
  .log { background:#0a0c10; border:1px solid #232a36; border-radius:8px; padding:12px; height:260px; overflow:auto; font-family:monospace; font-size:12px; margin-top:16px; white-space:pre-wrap; }
  .bar { height:6px; background:#232a36; border-radius:3px; margin-top:12px; overflow:hidden; }
  .bar > i { display:block; height:100%; width:0; background:#4f9cff; transition:width .3s; }
  .result { margin-top:16px; display:none; }
  .result a { color:#4f9cff; }
  .err { color:#ff6b6b; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🎙️ sub2voice</h1>
  <div class="sub">Tự động chuyển phụ đề trên màn hình video → giọng đọc tiếng Việt</div>

  <div class="drop" id="drop">
    📁 Kéo thả video vào đây hoặc <b>click để chọn</b><br>
    <small>MP4 / MKV / MOV · phụ đề phải nằm ở dưới cùng frame</small>
    <input type="file" id="file" accept="video/*" hidden>
  </div>

  <div class="opts">
    <label>Giọng đọc
      <select id="voice">
        <option value="vi-VN-NamMinhNeural">Nam Minh (nam)</option>
        <option value="vi-VN-HoaiMyNeural">Hoài My (nữ)</option>
      </select>
    </label>
    <label>Tốc độ
      <select id="rate">
        <option value="+5%">+5%</option>
        <option value="+12%" selected>+12%</option>
        <option value="+18%">+18%</option>
        <option value="+25%">+25%</option>
      </select>
    </label>
    <label>Âm lượng
      <input id="volume" type="number" step="0.1" value="2.2" style="width:80px">
    </label>
  </div>

  <button class="go" id="go" disabled>Bắt đầu chuyển đổi</button>

  <div class="bar"><i id="bar"></i></div>
  <div class="log" id="log"></div>

  <div class="result" id="result">
    ✅ Xong! <a id="dl" href="#" download>Tải video về</a>
  </div>
</div>

<script>
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const go = document.getElementById('go');
const log = document.getElementById('log');
const bar = document.getElementById('bar');
const result = document.getElementById('result');
const dl = document.getElementById('dl');
let selected = null;

drop.onclick = () => fileInput.click();
fileInput.onchange = e => pick(e.target.files[0]);
['dragover','dragenter'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('hover'); }));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('hover'); }));
drop.ondrop = e => pick(e.dataTransfer.files[0]);

function pick(f){
  if(!f) return;
  selected = f;
  drop.innerHTML = '🎬 Đã chọn: <b>'+f.name+'</b><br><small>'+Math.round(f.size/1024/1024*10)/10+' MB</small>';
  go.disabled = false;
}
function append(t, cls){ log.innerHTML += (cls?('<span class="'+cls+'">'):'')+t+(cls?'</span>':'')+'\\n'; log.scrollTop = log.scrollHeight; }

go.onclick = async () => {
  if(!selected) return;
  go.disabled = true; result.style.display='none'; log.innerHTML=''; bar.style.width='0%';
  const fd = new FormData();
  fd.append('video', selected);
  fd.append('voice', document.getElementById('voice').value);
  fd.append('rate', document.getElementById('rate').value);
  fd.append('volume', document.getElementById('volume').value);
  const r = await fetch('/upload', {method:'POST', body:fd});
  const j = await r.json();
  if(j.error){ append(j.error,'err'); go.disabled=false; return; }
  const job = j.job_id;
  const es = new EventSource('/progress/'+job);
  es.onmessage = e => {
    const d = JSON.parse(e.data);
    if(d.step) bar.style.width = Math.round(d.step/d.total*100)+'%';
    if(d.msg) append(d.msg);
    if(d.done){ es.close(); dl.href = '/download/'+job; result.style.display='block'; go.disabled=false; }
    if(d.error){ es.close(); append(d.error,'err'); go.disabled=false; }
  };
};
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(INDEX)

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("video")
    if not f:
        return jsonify(error="Thiếu file video"), 400
    job_id = uuid.uuid4().hex[:12]
    ext = os.path.splitext(f.filename)[1] or ".mp4"
    vpath = os.path.join(UPLOAD_DIR, job_id + ext)
    f.save(vpath)
    # lấy form values TRƯỚC khi spawn thread (request context không truyền được)
    voice = request.form.get("voice", "vi-VN-NamMinhNeural")
    rate = request.form.get("rate", "+12%")
    try:
        volume = float(request.form.get("volume", "2.2"))
    except ValueError:
        volume = 2.2
    q = queue.Queue()
    out_path = os.path.join(UPLOAD_DIR, job_id + "_vi.mp4")
    jobs[job_id] = {"queue": q, "out": out_path, "done": False, "error": None}

    def worker():
        try:
            def cb(step, total, msg):
                q.put({"step": step, "total": total, "msg": msg})
            sv.run_pipeline(vpath, out=out_path,
                            voice=voice, rate=rate, volume=volume,
                            fps=3.0, progress_cb=cb)
            q.put({"done": True})
            jobs[job_id]["done"] = True
        except Exception as e:
            import traceback
            traceback.print_exc()
            q.put({"error": str(e)})
            jobs[job_id]["error"] = str(e)
    threading.Thread(target=worker, daemon=True).start()
    return jsonify(job_id=job_id)

@app.route("/progress/<job_id>")
def progress(job_id):
    j = jobs.get(job_id)
    if not j:
        return jsonify(error="Job không tồn tại"), 404
    def gen():
        q = j["queue"]
        while True:
            try:
                item = q.get(timeout=30)
            except queue.Empty:
                if j["done"] or j["error"]:
                    break
                yield f"data: {json.dumps({'msg':'(đang chạy...)'})}\n\n"
                continue
            yield f"data: {json.dumps(item)}\n\n"
            if item.get("done") or item.get("error"):
                break
    return Response(gen(), mimetype="text/event-stream")

@app.route("/download/<job_id>")
def download(job_id):
    j = jobs.get(job_id)
    if not j or not os.path.exists(j["out"]):
        return "Chưa có file", 404
    return send_file(j["out"], as_attachment=True, download_name="sub2voice_output.mp4")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
