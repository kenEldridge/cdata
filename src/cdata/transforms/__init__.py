"""Canonical transforms shared by sources.

Sources emit already-normalized canonical dicts, so storage and downstream
consumers never see raw source columns. Transform modules own those canonical
shapes plus the normalizers and dedup logic that produce them.
"""
