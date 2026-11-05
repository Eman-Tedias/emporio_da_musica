"""Chat interface. Run with: streamlit run app/ui/streamlit_app.py (the API must be running)."""
import os
import re

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
WELCOME = "Oi! Sou o assistente virtual da Empório da Música. Posso ajudar com produtos, pedidos e políticas da loja."

MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<$])")

st.set_page_config(page_title="Empório da Música")


def show(role: str, content: str) -> None:
    # Streamlit renders text between two "$" as LaTeX, so "R$ 10 ou R$ 20" would turn into a formula.
    # Assistant answers keep their Markdown (bold, lists); customer text is shown literally.
    if role == "user":
        st.markdown(MARKDOWN_SPECIAL.sub(r"\\\1", content))
    else:
        st.markdown(content.replace("$", r"\$"))


def reset() -> None:
    st.session_state.session_id = None
    st.session_state.messages = [{"role": "assistant", "content": WELCOME}]
    st.session_state.last_trace = None


def ask(message: str) -> str:
    try:
        response = httpx.post(
            f"{API_URL}/chat",
            json={"session_id": st.session_state.session_id, "message": message},
            timeout=90,
        )
    except httpx.HTTPError:
        return "Não consegui falar com o atendimento agora. Tente de novo em instantes."
    if response.status_code == 429:
        return response.json()["detail"]
    if response.status_code != 200:
        return "Algo deu errado do nosso lado. Tente de novo em instantes."
    body = response.json()
    st.session_state.session_id = body["session_id"]
    st.session_state.last_trace = body["trace"]
    return body["answer"]


if "messages" not in st.session_state:
    reset()

with st.sidebar:
    st.header("Empório da Música")
    st.caption("Rua 14 de Maio, 3200, Centro, Campo Grande - MS")
    st.button("Nova conversa", on_click=reset, use_container_width=True)
    show_trace = st.toggle("Mostrar trace do último turno")
    if show_trace and st.session_state.last_trace:
        st.json(st.session_state.last_trace, expanded=False)

st.title("Atendimento")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        show(message["role"], message["content"])

if prompt := st.chat_input("Digite sua mensagem"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        show("user", prompt)
    with st.chat_message("assistant"):
        with st.spinner("Consultando..."):
            answer = ask(prompt)
        show("assistant", answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.rerun()
