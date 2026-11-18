"""Grounded Q&A and cross-document verification."""

from .ask import NOT_FOUND, answer_question
from .verify import verify_documents

__all__ = ["NOT_FOUND", "answer_question", "verify_documents"]
