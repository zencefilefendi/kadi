"""Kadı: a calibrated judge that sits in front of your frontier model.

Small, routine decisions are answered locally, with a statistical guarantee on
how often they disagree with the oracle. Everything else is escalated, and each
oracle answer trains the local model.
"""
from .engine import Decision, Kadi, Pending
from .oracles import AnthropicOracle, FunctionOracle, OpenAICompatibleOracle, OracleError, Verdict
from .questions import Binary, Choice, Question, Score
from .redact import DEFAULT_REDACTOR, Redactor

__all__ = ["Kadi", "Decision", "Pending", "Question", "Choice", "Binary", "Score",
           "AnthropicOracle", "OpenAICompatibleOracle", "FunctionOracle", "OracleError", "Verdict",
           "Redactor", "DEFAULT_REDACTOR"]
__version__ = "0.5.1"
