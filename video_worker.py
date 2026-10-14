"""Standalone local video processor. Run with an isolated Python environment, never inside bpy."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import urllib.request
import venv

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
TOOLS_VERSION = '2'


def environment_python(folder):
    return Path(folder) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def setup(folder):
    folder = Path(folder)
    print("Creating local video environment", flush=True)
    venv.EnvBuilder(with_pip=True).create(folder / "python")
    python = environment_python(folder / "python")
    (folder/'ready.json').unlink(missing_ok=True)
    # All OpenCV wheels own cv2. MediaPipe requires contrib; installing the main
    # package alongside it lets an unpinned contrib wheel overwrite the runtime.
    subprocess.run([str(python), '-m', 'pip', 'uninstall', '-y', 'opencv-python',
                    'opencv-python-headless', 'opencv-contrib-python-headless', 'opencv-contrib-python'], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                    "mediapipe==0.10.35", "opencv-contrib-python==4.13.0.92"], check=True)
    subprocess.run([str(python),'-m','pip','check'],check=True)
    model = folder / "face_landmarker.task"
    temp = model.with_suffix(".download")
    print("Downloading face tracking model", flush=True)
    with urllib.request.urlopen(MODEL_URL, timeout=120) as response, temp.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    temp.replace(model)
    subprocess.run([str(python), str(Path(__file__).resolve()), "--check", str(model)], check=True)
    (folder/'ready.json').write_text(json.dumps({'version':TOOLS_VERSION}),encoding='utf-8')
    print("Video tools ready", flush=True)


def tracker(model):
    import mediapipe as mp
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_faces=1, output_face_blendshapes=True)
    return mp.tasks.vision.FaceLandmarker.create_from_options(options)


def process(video, model, output, progress):
    import cv2
    import mediapipe as mp
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError("Cannot open this video. Try an MP4 encoded with H.264.")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(fps) or fps <= 0:
        cap.release()
        raise ValueError("Video has no valid frame rate")
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    detected = index = 0
    last_ms = -1
    partial = Path(output).with_suffix(".partial")
    try:
        with tracker(model) as detector, partial.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({"fps": fps, "frames": count}) + "\n")
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                # Preserve presentation time when available (including variable-rate video).
                pts = cap.get(cv2.CAP_PROP_POS_MSEC)
                ms = round(pts) if math.isfinite(pts) and pts > last_ms else round(index * 1000 / fps)
                ms = max(last_ms + 1, ms)
                last_ms = ms
                height, width = frame.shape[:2]
                if max(height, width) > 1280:
                    ratio = 1280 / max(height, width)
                    frame = cv2.resize(frame, (round(width * ratio), round(height * ratio)))
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ms)
                values = {}
                if result.face_blendshapes:
                    values = {c.category_name: float(c.score) for c in result.face_blendshapes[0]
                              if c.category_name != "_neutral"}
                    detected += 1
                # No face = neutral; never carry a smile through an empty section of video.
                stream.write(json.dumps({"time": ms / 1000, "values": values}) + "\n")
                index += 1
                if index % 10 == 0:
                    Path(progress).write_text(f"Processing frame {index} / {count or '?'}", encoding="utf-8")
        if not index or not detected:
            raise ValueError("No face detected. Use a well-lit video with one clearly visible face.")
        partial.replace(output)
        Path(progress).write_text(f"Tracked face in {detected} / {index} frames", encoding="utf-8")
    finally:
        cap.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup")
    parser.add_argument("--check")
    parser.add_argument("--video")
    parser.add_argument("--model")
    parser.add_argument("--output")
    parser.add_argument("--progress")
    args = parser.parse_args()
    try:
        if args.setup:
            setup(args.setup)
        elif args.check:
            from importlib.metadata import version
            if version('mediapipe') != '0.10.35' or version('opencv-contrib-python') != '4.13.0.92':
                raise ValueError('Video package versions do not match; use Repair Video Tools')
            with tracker(args.check):
                pass
        else:
            process(args.video, args.model, args.output, args.progress)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
