"""
LLM Copilot client — Claude API wrapper for analytical insights.

Scope: ANALYTICAL ONLY.
  Allowed:  regime classification, risk flags, post-trade analysis, recommendations
  Forbidden: order placement, parameter writes, live trading decisions

Output: validated JSON conforming to the schema in prompts.py.
"""
from __future__ import annotations

import json
import os

MODEL = "claude-sonnet-4-6"


def analyze_backtest(
    strategy_key: str,
    strategy_label: str,
    symbol: str,
    metrics: dict,
    equity_curve: list[dict],
    optimization: dict | None = None,
) -> dict:
    """
    Send backtest results to Claude for structured analysis.

    Returns a dict with keys: regime, regime_confidence, regime_label,
    regime_explanation, risk_flags, strategy_assessment, strengths,
    weaknesses, recommendations, gate2_readiness, gate2_rationale.

    Raises RuntimeError if ANTHROPIC_API_KEY is not set.
    """
    import anthropic
    from src.llm.prompts import build_analysis_prompt

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to alphasmart/.env as: ANTHROPIC_API_KEY=sk-ant-..."
        )

    prompt = build_analysis_prompt(
        strategy_key=strategy_key,
        strategy_label=strategy_label,
        symbol=symbol,
        metrics=metrics,
        equity_curve=equity_curve,
        optimization=optimization,
    )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude adds them
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: wrap raw text as assessment to avoid complete failure
        result = {
            "regime": "unknown",
            "regime_confidence": 0.0,
            "regime_label": "Analysis Incomplete",
            "regime_explanation": "JSON parsing failed — raw response returned.",
            "risk_flags": [],
            "strategy_assessment": raw[:500],
            "strengths": [],
            "weaknesses": [],
            "recommendations": [],
            "gate2_readiness": "not_ready",
            "gate2_rationale": "Could not parse LLM response.",
        }

    return result
