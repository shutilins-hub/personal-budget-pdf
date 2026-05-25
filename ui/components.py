from __future__ import annotations

import streamlit as st


APP_CSS = """
<style>
    .stApp { background: #ffffff; color: #111827; }
    [data-testid="stHeader"] { background: rgba(255, 255, 255, 0.92); }
    .block-container { max-width: 1180px; padding-top: 1.6rem; }
    .budget-hero { margin: 0 0 18px; }
    .budget-hero h1 { font-size: 34px; margin: 0 0 6px; letter-spacing: -0.03em; }
    .budget-sub { color: #6b7280; font-size: 15px; }
    .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 14px 0; }
    .primary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 16px 0 10px; }
    .primary-card {
        background: #ffffff; border: 1px solid #dbe3ef; border-radius: 24px;
        padding: 22px; box-shadow: 0 18px 42px rgba(15, 23, 42, .08);
    }
    .primary-card.is-plan { border-color: #bfdbfe; }
    .primary-card.is-spent { border-color: #c7d2fe; }
    .primary-card.is-left.status-danger { border-color: #fecaca; }
    .primary-card.is-left.status-warn { border-color: #fed7aa; }
    .primary-card.is-left.status-good { border-color: #bbf7d0; }
    .primary-label { color: #475569; font-size: 14px; margin-bottom: 10px; }
    .primary-value { color: #0f172a; font-size: 38px; line-height: 1; font-weight: 820; letter-spacing: -0.04em; }
    .primary-hint { color: #64748b; font-size: 13px; margin-top: 10px; }
    .overview-progress { margin: 4px 0 18px; }
    .overview-caption { color: #64748b; font-size: 14px; margin-top: 8px; }
    .secondary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 10px 0; }
    .utility-line {
        color: #64748b; font-size: 13px; margin: 8px 0 20px; padding: 10px 0;
        border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb;
    }
    .metric-card, .section-card, .attention-card {
        background: #ffffff; border: 1px solid #e5e7eb; border-radius: 22px;
        padding: 18px; box-shadow: 0 12px 30px rgba(17, 24, 39, .06);
    }
    .metric-label { color: #6b7280; font-size: 13px; margin-bottom: 8px; }
    .metric-value { font-size: 25px; font-weight: 750; letter-spacing: -0.02em; }
    .metric-hint { color: #6b7280; font-size: 13px; margin-top: 8px; }
    .status-good { border-color: #bbf7d0; }
    .status-warn { border-color: #fde68a; }
    .status-danger { border-color: #fecaca; }
    .section-card { margin: 12px 0 20px; }
    .progress-row { padding: 13px 0; border-bottom: 1px solid #e5e7eb; }
    .progress-row:last-child { border-bottom: 0; }
    .progress-top { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
    .progress-top span { white-space: nowrap; color: #6b7280; font-variant-numeric: tabular-nums; }
    .progress-bottom { color: #6b7280; font-size: 13px; margin-top: 6px; }
    .bar { height: 9px; background: #eef2f7; border-radius: 99px; overflow: hidden; margin-top: 9px; }
    .bar div { height: 100%; background: #111827; border-radius: 99px; }
    .progress-warn .bar div { background: #d97706; }
    .progress-danger .bar div { background: #dc2626; }
    .progress-nolimit .bar div { background: #9ca3af; }
    .progress-status { font-size: 12px; border-radius: 999px; padding: 4px 9px; background: #eef2f7; color: #334155; }
    .progress-warn .progress-status { background: #fff7ed; color: #c2410c; }
    .progress-danger .progress-status { background: #fef2f2; color: #b91c1c; }
    .progress-nolimit .progress-status { background: #f3f4f6; color: #4b5563; }
    .step-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 12px 0 18px; }
    .step { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 18px; padding: 12px 14px; color: #6b7280; }
    .step-active { color: #111827; border-color: #111827; }
    .step-done { color: #166534; border-color: #bbf7d0; }
    .attention-card { margin: 8px 0; }
    .attention-title { font-weight: 750; margin-bottom: 4px; }
    .attention-text { color: #6b7280; }
    .attention-action-card {
        background: #ffffff; border: 1px solid #fde68a; border-radius: 20px;
        padding: 16px 18px; box-shadow: 0 10px 26px rgba(17, 24, 39, .05); margin: 10px 0 4px;
    }
    .attention-action-card.status-danger { border-color: #fecaca; }
    .attention-action-card.status-good { border-color: #bbf7d0; }
    .attention-action-title { font-weight: 780; color: #111827; margin-bottom: 6px; }
    .attention-action-text { color: #64748b; font-size: 15px; }
    .category-card {
        background: #ffffff; border: 1px solid #e5e7eb; border-radius: 20px;
        padding: 17px 18px; box-shadow: 0 10px 28px rgba(17, 24, 39, .045); margin: 12px 0 4px;
    }
    .category-card.category-warn { border-color: #fed7aa; }
    .category-card.category-danger { border-color: #fecaca; }
    .category-card.category-review { border-color: #fde68a; }
    .category-card.category-nolimit { border-color: #d1d5db; }
    .category-head { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; }
    .category-title { font-weight: 800; color: #111827; font-size: 18px; }
    .category-amount { color: #4b5563; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .category-foot { display: flex; justify-content: space-between; gap: 12px; color: #64748b; font-size: 14px; margin-top: 7px; }
    .category-status { font-weight: 700; }
    .category-danger .category-status { color: #b91c1c; }
    .category-warn .category-status { color: #c2410c; }
    .category-review .category-status { color: #a16207; }
    .category-nolimit .category-status { color: #4b5563; }
    .category-danger .bar div { background: #dc2626; }
    .category-warn .bar div { background: #d97706; }
    .category-review .bar div { background: #ca8a04; }
    .category-nolimit .bar div { background: #9ca3af; }
    @media (max-width: 900px) { .metric-grid, .primary-grid, .secondary-grid, .step-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 560px) { .metric-grid, .primary-grid, .secondary-grid, .step-strip { grid-template-columns: 1fr; } .progress-top { display:block; } }
</style>
"""


def apply_app_style() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)


def money(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def pct(value: float) -> str:
    return f"{value:.0%}"


def render_metric_card(label: str, value: str, hint: str | None = None, status: str | None = None) -> None:
    status_class = f" status-{status}" if status else ""
    hint_html = f'<div class="metric-hint">{hint}</div>' if hint else ""
    st.markdown(
        f'<div class="metric-card{status_class}"><div class="metric-label">{label}</div><div class="metric-value">{value}</div>{hint_html}</div>',
        unsafe_allow_html=True,
    )


def render_metric_grid(cards: list[dict]) -> None:
    html = ['<div class="metric-grid">']
    for card in cards:
        status_class = f" status-{card.get('status')}" if card.get("status") else ""
        hint_html = f'<div class="metric-hint">{card.get("hint")}</div>' if card.get("hint") else ""
        html.append(
            f'<div class="metric-card{status_class}"><div class="metric-label">{card["label"]}</div><div class="metric-value">{card["value"]}</div>{hint_html}</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def category_status_meta(fact: float, plan: float) -> dict[str, str | float]:
    if plan > 0:
        usage = fact / plan
        if usage > 1:
            return {"label": "перерасход", "css": "progress-danger", "card_css": "category-danger", "bottom": f"Перерасход: {money(fact - plan)}", "usage": usage, "rank": 1}
        if usage >= 0.8:
            return {"label": "близко к лимиту", "css": "progress-warn", "card_css": "category-warn", "bottom": f"Осталось: {money(plan - fact)}", "usage": usage, "rank": 2}
        return {"label": "в норме", "css": "", "card_css": "", "bottom": f"Осталось: {money(plan - fact)}", "usage": usage, "rank": 5}
    if fact > 0:
        return {"label": "лимит не задан", "css": "progress-nolimit", "card_css": "category-nolimit", "bottom": "Есть расходы без плана", "usage": 1.0, "rank": 4}
    return {"label": "план не задан", "css": "progress-nolimit", "card_css": "category-nolimit", "bottom": "Нет расходов", "usage": 0.0, "rank": 6}


def render_progress_row(category: str, fact: float, plan: float) -> str:
    meta = category_status_meta(fact, plan)
    width = min(100, max(0, float(meta["usage"]) * 100))
    row_class = f" {meta['css']}" if meta["css"] else ""
    return (
        f'<div class="progress-row{row_class}">'
        f'<div class="progress-top"><b>{category}</b><span>{money(fact)} / {money(plan)} · <span class="progress-status">{meta["label"]}</span></span></div>'
        f'<div class="bar"><div style="width:{width:.1f}%"></div></div>'
        f'<div class="progress-bottom">{meta["bottom"]}</div>'
        f'</div>'
    )


def category_status(fact: float, plan: float) -> str:
    return str(category_status_meta(fact, plan)["label"])


def render_category_summary_row(category: str, fact: float, plan: float) -> str:
    return render_progress_row(category, fact, plan)


def render_attention_card(title: str, text: str, status: str | None = None) -> None:
    status_class = f" status-{status}" if status else ""
    st.markdown(
        f'<div class="attention-card{status_class}"><div class="attention-title">{title}</div><div class="attention-text">{text}</div></div>',
        unsafe_allow_html=True,
    )


def render_section_card(title: str, body: str) -> None:
    st.markdown(f'<div class="section-card"><h3>{title}</h3>{body}</div>', unsafe_allow_html=True)
