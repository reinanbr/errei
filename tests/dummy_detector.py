"""Detector externo de exemplo para testes do adapter."""

from __future__ import annotations

LOADED: list[str] = []


class Detector:
    name = "dummy"
    uses_network = False

    def __init__(self) -> None:
        LOADED.append("ok")

    def score(self, text: str) -> float:
        return 0.42
