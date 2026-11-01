"""Lorekeeper `ml` sidecar: one shared process serving embeddings and NER.

Standalone on purpose: nothing here imports the backend `app` package, and
the heavy libraries (torch, sentence_transformers, spacy) are imported only
inside the real model loaders in `ml_service.models`, so the HTTP app can be
tested with fake models and no ML stack installed.
"""
