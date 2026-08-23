# sub2voice — Video Subtitle → Vietnamese Voiceover

Tự động chuyển **phụ đề burned-in** (chữ nằm trên màn hình video, không có file SRT)
thành **voiceover tiếng Việt**, rồi ghép lại thành video mới.

Ví dụ: video bodycam cảnh sát Mỹ có phụ đề VN + tiếng Anh gốc →
đầu ra: video có giọng đọc tiếng Việt, tiếng Anh gốc bị tắt.

## Nguyên lý

1. Extract frame dày (mặc định 3 fps) từ video.
2. Crop vùng phụ đề (cuối frame), phóng to để dễ đọc.
3. Lọc bỏ frame trùng (cùng 1 câu) → chỉ giữ 1 frame đại diện mỗi câu.
4. Dùng **Vision API** đọc text tiếng Việt từ từng frame.
5. TTS (edge-tts, giọng Nam Minh mặc định) từng câu, lồng đúng timeline.
6. Ghép audio VN vào video, mute tiếng gốc.

## Cài đặt

```bash
pip install pillow edge-tts requests
# ffmpeg phải có sẵn (apt install ffmpeg / brew install ffmpeg)
```

## Cấu hình Vision

App dùng OpenAI-compatible Vision API. Set env:

```bash
export VISION_API_KEY="sk-..."
export VISION_BASE_URL="https://api.openai.com/v1"   # hoặc base url của nhà cung cấp khác
export VISION_MODEL="gpt-4o-mini"                    # model có khả năng nhìn
# Hoặc dùng OpenRouter MIỄN PHÍ:
export VISION_PROVIDER=openrouter
export VISION_API_KEY="sk-or-..."      # lấy tại openrouter.ai/keys
export VISION_MODEL="google/gemini-flash-1.5"
```

> Muốn chạy local: dùng llama.cpp / ollama có vision, set
> `VISION_BASE_URL=http://localhost:11434/v1` và `VISION_MODEL=llava` (hoặc model tương đương).

## Dùng

### Web UI (khuyên dùng)

```bash
pip install -r requirements.txt
export VISION_API_KEY="sk-..."
python3 app.py
# mở http://localhost:5000 → kéo-thả video, chọn giọng/tốc độ/âm lượng, bấm "Bắt đầu"
```

UI hiển thị progress realtime (từng bước: extract → lọc trùng → đọc vision → TTS → ghép),
khi xong có nút tải video về. Không cần dùng terminal.

### CLI

```bash
# Cơ bản
python3 sub2voice.py video.mp4 --out video_vi.mp4

# Đổi giọng nữ, đọc nhanh hơn
python3 sub2voice.py video.mp4 --voice vi-VN-HoaiMyNeural --rate +18%

# To hơn / nhỏ hơn
python3 sub2voice.py video.mp4 --volume 3.0
```

### Tham số

| Arg | Mặc định | Ý nghĩa |
|-----|----------|---------|
| `video` | (bắt buộc) | đường dẫn video gốc |
| `--out` | `output_vi.mp4` | video đầu ra |
| `--voice` | `vi-VN-NamMinhNeural` | giọng edge-tts |
| `--rate` | `+12%` | tốc độ đọc |
| `--volume` | `2.2` | khuếch đại audio tổng |
| `--fps` | `3.0` | số frame/giây extract |

## Lưu ý

- Phụ đề phải nằm ở **dưới cùng** frame (vùng 80%–97% chiều cao). Video có phụ đề
  giữa màn hình cần chỉnh `sub_band()` (top/bot).
- Nếu video dài, bước Vision gọi API nhiều lần → tốn token. Mỗi câu chỉ gọi 1 lần.
- Chất lượng nhận diện phụ đề phụ thuộc độ phân giải + độ tương phản chữ.

## License

MIT
