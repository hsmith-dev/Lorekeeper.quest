"""Lorekeeper `stt` sidecar: one shared process serving speech-to-text.

Standalone on purpose: nothing here imports the backend `app` package, and
the heavy libraries (faster_whisper, ctranslate2, av) are imported only inside
the real model and decoder functions in `stt_service.models`, so the HTTP app
can be tested with a fake model and no speech stack installed.
"""
