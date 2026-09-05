"""Jinja2-backed Markdown rendering for dynamic output schemas."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.dynamic.criticality import CriticalityState
from src.dynamic.mismatch import MismatchMap
from src.dynamic.provider_integrity import ProviderIntegrityPanel
from src.dynamic.research_note import ResearchNote
from src.dynamic.signal_card import SignalCard

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=()),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_signal_card(card: SignalCard) -> str:
    return str(_env.get_template("signal_card.md.j2").render(card=card)).strip() + "\n"


def render_mismatch_map(mm: MismatchMap) -> str:
    return str(_env.get_template("mismatch_map.md.j2").render(mm=mm)).strip() + "\n"


def render_criticality(cs: CriticalityState) -> str:
    return str(_env.get_template("criticality.md.j2").render(cs=cs)).strip() + "\n"


def render_provider_integrity(pip: ProviderIntegrityPanel) -> str:
    return str(_env.get_template("provider_integrity.md.j2").render(pip=pip)).strip() + "\n"


def render_research_note(note: ResearchNote) -> str:
    signal_cards_section = "\n\n".join(render_signal_card(c) for c in note.signal_cards)
    mismatch_section = render_mismatch_map(note.mismatch_map)
    criticality_section = render_criticality(note.criticality)
    provider_section = render_provider_integrity(note.provider_integrity)
    return (
        str(_env.get_template("research_note.md.j2").render(
            note=note,
            signal_cards_section=signal_cards_section,
            mismatch_section=mismatch_section,
            criticality_section=criticality_section,
            provider_section=provider_section,
        ))
        .strip()
        + "\n"
    )
