"""Import faster-whisper in an image that has no PyAV.

Why: PyAV's wheels bundle an FFmpeg linked against GPL libx264/libx265, and
only permissive code may be linked into a Lorekeeper process. So the stt image
never installs `av` (requirements.txt header), and audio is decoded by the
`ffmpeg` CLI as a separate process (stt_service.models.decode_container).

The catch: faster_whisper/__init__.py imports faster_whisper.audio, whose
first line is a bare `import av`. In faster-whisper 1.2.1 `av` is used only
inside decode_audio() and its helpers, which this sidecar never calls: it
always hands WhisperModel.transcribe a float32 numpy array.

So, only when `av` is genuinely not installed, this registers an inert
placeholder module under sys.modules["av"] for this process, then imports
faster_whisper. Nothing in site-packages is touched. Any attribute access on
the placeholder raises AvNotInstalled, so a code path that did try to decode
through PyAV fails loudly instead of silently. `python -c "import av"` in a
fresh interpreter still fails, which the Dockerfile guard checks.
"""

from __future__ import annotations

import importlib.util
import sys
import types

PLACEHOLDER_ATTR = "__lorekeeper_av_placeholder__"


class AvNotInstalled(RuntimeError):
    """Something tried to use PyAV, which this image deliberately lacks."""


class _AvPlaceholder(types.ModuleType):
    def __getattr__(self, name: str):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise AvNotInstalled(
            f"av.{name}: PyAV is deliberately not installed in the stt image (its bundled "
            "FFmpeg links GPL code); decode audio with stt_service.models.decode_container"
        )


def _install_placeholder() -> None:
    if "av" in sys.modules:
        return
    if importlib.util.find_spec("av") is not None:
        return  # a real PyAV is installed (a dev venv): leave it alone
    mod = _AvPlaceholder("av", "Inert placeholder: PyAV is not installed (see stt_service.whisper_loader).")
    setattr(mod, PLACEHOLDER_ATTR, True)
    sys.modules["av"] = mod


def whisper_model_class():
    """faster_whisper.WhisperModel, importable without PyAV."""
    _install_placeholder()
    from faster_whisper import WhisperModel

    return WhisperModel
