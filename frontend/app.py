"""Import-safe placeholder for the Streamlit application."""


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Meta KPI Calculator", layout="wide")
    st.title("Meta KPI Calculator")
    st.info("Scaffold concluído. O painel será implementado em uma etapa futura.")


if __name__ == "__main__":
    main()

