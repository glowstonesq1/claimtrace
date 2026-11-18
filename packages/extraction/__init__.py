"""Structured extraction: rules baseline, optional LLM extractor, amendment application."""

from .analyze import analyze_document
from .apply import apply_amendments
from .rules import EXTRACTOR_VERSION, extract_rules

__all__ = ["EXTRACTOR_VERSION", "analyze_document", "apply_amendments", "extract_rules"]
