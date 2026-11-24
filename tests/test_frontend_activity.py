"""Exercise the pending operation through actual Streamlit reruns."""

from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_activity_retry_and_abandonment(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    from frontend import app

    attempts = []
    outcomes = iter(["timeout", "503", "422", None])

    def request(_client, method, path, **kwargs):
        attempts.append((method, path, kwargs))
        return None, next(outcomes)

    monkeypatch.setattr(app, "_request_result", request)
    screen = AppTest.from_string("""
import streamlit as st
from frontend.app import _lead_care

if notice := st.session_state.pop("crm_care_notice", None):
    getattr(st, notice[0])(notice[1])
_lead_care(st, None, {"id": 7, "commercial_status": "NEW"})
""").run()

    def click(label):
        next(button for button in screen.button if button.label == label).click().run()
        assert not screen.exception

    def submit(note):
        screen.text_area[0].set_value(note)
        click("Registrar atividade")

    submit("Observação inicial")
    click("Reenviar a mesma atividade")
    assert attempts[0] == attempts[1]
    assert any("não desfaz" in caption.value for caption in screen.caption)
    click("Abandonar tentativa")
    assert len(attempts) == 2
    assert any("Confira o histórico" in warning.value for warning in screen.warning)
    submit("Observação corrigida")
    assert any("Revise o conteúdo" in warning.value for warning in screen.warning)
    assert not any(button.label == "Reenviar a mesma atividade" for button in screen.button)
    submit("Nova atividade")
    assert any("Atividade registrada" in success.value for success in screen.success)
    assert len({entry[2]["headers"]["Idempotency-Key"] for entry in attempts}) == 3
