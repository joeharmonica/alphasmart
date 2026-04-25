"""
Prompt templates for AlphaSMART LLM Copilot.

All prompts instruct Claude to return valid JSON only.
The LLM has ZERO ability to place orders or modify strategy parameters.
"""
from __future__ import annotations

import json


def _summarize_equity_curve(equity_curve: list[dict], n_samples: int = 12) -> str:
    """Sample evenly spaced points from the equity curve for compact prompt context."""
    if not equity_curve:
        return "  No equity data"
    step = max(1, len(equity_curve) // n_samples)
    sampled = equity_curve[::step][:n_samples]
    return "\n".join(f"  {p['date']}: ${p['equity']:,.0f}" for p in sampled)


def build_analysis_prompt(
    strategy_key: str,
    strategy_label: str,
    symbol: str,
    metrics: dict,
    equity_curve: list[dict],
    optimization: dict | None = None,
) -> str:
    eq_summary = _summarize_equity_curve(equity_curve)

    opt_section = ""
    if optimization and not optimization.get("error"):
        wf = optimization.get("walk_forward", [])
        wf_summary = json.dumps(
            [
                {
                    "fold": w["fold"],
                    "is_sharpe": w["is_sharpe"],
                    "oos_sharpe": w["oos_sharpe"],
                    "is_period": w["is_period"],
                    "oos_period": w["oos_period"],
                }
                for w in wf
            ],
            indent=2,
        )
        opt_section = f"""

## Parameter Optimization Results
- Combinations tested: {optimization.get('total_combos', '?')}
- Best in-sample Sharpe: {optimization.get('best_sharpe', '?')}
- Best params: {json.dumps(optimization.get('best_params', {}))}
- Overfitting score (mean OOS/IS Sharpe ratio): {optimization.get('overfitting_score', 'N/A')}
- Gate 2 pass (≥0.70 required): {optimization.get('gate2_pass', False)}

Walk-forward folds:
{wf_summary}"""

    return f"""You are AlphaSMART's analytical copilot. Your role is STRICTLY ANALYTICAL.
You cannot place orders, modify parameters, or affect live or paper trading in any way.

Analyze the following backtest results for {strategy_label} ({strategy_key}) on {symbol}.

## Performance Metrics
- Sharpe Ratio:    {metrics.get('sharpe', 0):.3f}
- Sortino Ratio:   {metrics.get('sortino', 0):.3f}
- CAGR:            {metrics.get('cagr', 0):.2%}
- Max Drawdown:    {metrics.get('max_drawdown', 0):.2%}
- Win Rate:        {metrics.get('win_rate', 0):.2%}
- Profit Factor:   {metrics.get('profit_factor', 0):.2f}
- Total Return:    {metrics.get('total_return', 0):.2%}
- Trade Count:     {metrics.get('trade_count', 0)}
- Exposure:        {metrics.get('exposure', 0):.2%}
- Avg Trade:       {metrics.get('avg_trade_return', 0):.2%}
- Best Trade:      {metrics.get('best_trade', 0):.2%}
- Worst Trade:     {metrics.get('worst_trade', 0):.2%}
- Gate 1 Pass:     {metrics.get('gate1_pass', False)}

## Equity Curve (sampled)
{eq_summary}
{opt_section}

Respond with ONLY valid JSON matching this exact schema. No markdown, no text outside the JSON object:

{{
  "regime": "trending_bull | trending_bear | ranging | volatile | mixed",
  "regime_confidence": <float 0.0-1.0>,
  "regime_label": "<short 2-4 word label>",
  "regime_explanation": "<1-2 sentences explaining the detected market regime>",
  "risk_flags": [
    {{
      "severity": "high | medium | low",
      "flag": "<short flag name>",
      "detail": "<one sentence explaining the risk>"
    }}
  ],
  "strategy_assessment": "<2-3 sentences overall assessment of this strategy's performance>",
  "strengths": ["<strength 1>", "<strength 2>"],
  "weaknesses": ["<weakness 1>", "<weakness 2>"],
  "recommendations": ["<actionable suggestion 1>", "<actionable suggestion 2>"],
  "gate2_readiness": "ready | conditional | not_ready",
  "gate2_rationale": "<brief explanation of Gate 2 readiness based on overfitting score and stability>"
}}"""
