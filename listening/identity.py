"""Exact identity normalization; this deliberately does not fuzzy-match names."""
import unicodedata


def normalize_name(value):
    return unicodedata.normalize("NFC", value).strip().casefold()
