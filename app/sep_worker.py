"""
Persistent stem-separation worker (spawned by server.py).

Loads Demucs models once and keeps them in memory, so queued jobs skip the
torch import + model load that a fresh `python -m demucs` pays every time.

Self-healing / performance:
  - uses an NVIDIA GPU (CUDA) automatically when available, falls back to CPU
    on out-of-memory or any CUDA error;
  - loads only the sub-model it needs (1 stem -> htdemucs_ft specialist);
  - deletes and re-downloads a corrupted model checkpoint once.

Protocol (one JSON object per line):
  stdin : {"cmd": "preload", "stems": [...]}
          {"cmd": "separate", "audio": path, "out": dir, "stems": [...],
           "overlap": 0.1, "threads": null}
  stdout: PROGRESS <0-100>      during separation
          DONE <json>           {"files": [...], "device": "cpu"|"cuda"}
          ERROR <message>
"""

import glob
import json
import os
import sys
import traceback
import types

import torch
import demucs.apply as dapply
from demucs.apply import apply_model
from demucs.audio import AudioFile, save_audio
from demucs.pretrained import get_model

# htdemucs = one 4-source model; htdemucs_ft = 4 models, each fine-tuned for one stem.
HTDEMUCS = "955717e8"
SPECIALIST = {"drums": "f7e0c4bc", "bass": "d12395a8", "other": "92cfc3b6", "vocals": "04573f0d"}
STEMS = ("vocals", "drums", "bass", "other")

_models = {}
_cuda_ok = torch.cuda.is_available()
if _cuda_ok:
    torch.backends.cudnn.benchmark = True   # same chunk size every time -> faster kernels


def out(line):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# Replace demucs' tqdm by a silent iterator that reports progress on stdout.
def _progress(iterable, **kw):
    items = list(iterable)
    n = max(len(items), 1)
    for i, it in enumerate(items):
        yield it
        out(f"PROGRESS {100.0 * (i + 1) / n:.1f}")


dapply.tqdm = types.SimpleNamespace(tqdm=_progress)


def _purge_checkpoint(sig):
    ckdir = os.path.join(torch.hub.get_dir(), "checkpoints")
    for f in glob.glob(os.path.join(ckdir, f"{sig}-*")):
        try:
            os.remove(f)
        except OSError:
            pass


def load(sig):
    if sig not in _models:
        try:
            m = get_model(sig)
        except Exception:  # noqa: BLE001 - corrupted/partial download -> retry once
            _purge_checkpoint(sig)
            m = get_model(sig)
        m.eval()
        _models[sig] = m
    return _models[sig]


def sig_for(stems):
    """1 stem -> the htdemucs_ft sub-model fine-tuned for that stem (lighter and
    better for that stem). 2+ stems -> htdemucs (one pass, 4 sources)."""
    return SPECIALIST[stems[0]] if len(stems) == 1 else HTDEMUCS


def _apply(model, wav, overlap, device):
    with torch.inference_mode():
        return apply_model(model, wav[None], device=device, shifts=1, split=True,
                           overlap=overlap, progress=True)[0]


def separate(job):
    global _cuda_ok
    stems = [s for s in job["stems"] if s in STEMS]
    if not stems:
        raise ValueError("no stem selected")
    model = load(sig_for(stems))
    if job.get("threads"):
        torch.set_num_threads(int(job["threads"]))

    wav = AudioFile(job["audio"]).read(streams=0, samplerate=model.samplerate,
                                       channels=model.audio_channels)
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    wav = (wav - mean) / std
    overlap = float(job.get("overlap", 0.1))

    device = "cuda" if _cuda_ok else "cpu"
    try:
        res = _apply(model, wav, overlap, device)
    except Exception as e:  # noqa: BLE001
        if device != "cuda":
            raise
        # GPU too small / driver issue: stay on CPU from now on.
        sys.stderr.write(f"CUDA failed, falling back to CPU: {e}\n")
        _cuda_ok = False
        model.to("cpu")
        torch.cuda.empty_cache()
        out("PROGRESS 0")
        device = "cpu"
        res = _apply(model, wav, overlap, device)
    res = res.cpu() * std + mean

    os.makedirs(job["out"], exist_ok=True)
    files = []
    for name, src in zip(model.sources, res):
        if name in stems:
            path = os.path.join(job["out"], name + ".wav")
            save_audio(src, path, samplerate=model.samplerate)
            files.append(path)
    return {"files": files, "device": device}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
            if job.get("cmd") == "preload":
                stems = [s for s in job.get("stems", []) if s in STEMS] or list(STEMS)
                load(sig_for(stems))
                out("DONE {}")
            else:
                out("DONE " + json.dumps(separate(job)))
        except MemoryError:
            out("ERROR Not enough memory to separate this track")
        except Exception as e:  # noqa: BLE001
            out("ERROR " + (str(e) or repr(e)).replace("\n", " ")[:500])
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
