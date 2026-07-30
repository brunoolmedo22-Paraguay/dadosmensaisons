# Dados Mensais ONS — Balanço + EAR

Aplicação Streamlit unificada para baixar e analisar duas bases oficiais do ONS:

- **Balanço Energético por Subsistema**;
- **Energia Armazenada (EAR) diária por Subsistema**.

## Funcionamento

1. Selecione o intervalo de anos.
2. Clique em **Baixar dados do ONS**. A aplicação obtém e valida os arquivos Parquet anuais das duas bases.
3. No seletor segmentado entre o painel de período e o painel de resultados, marque **Balanço**, **EAR** ou as duas bases.
4. Escolha o subsistema e a discretização: **diária**, **mensal** ou **anual**.
5. Visualize os dados em uma única tabela e baixe um único CSV com as mesmas colunas exibidas.

A opção horária foi removida da interface porque a base de EAR é diária. O Balanço continua sendo lido em sua resolução original e é consolidado internamente para a discretização selecionada.

## Execução local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Arquivos principais

- `app.py`: interface e fluxo unificado;
- `balanco_ons.py`: processamento do Balanço Energético;
- `ons_download.py`: download do Balanço Energético;
- `ear_processing.py`: processamento da EAR;
- `ear_download.py`: download da EAR;
- `unified_ons.py`: junção temporal, tabela e CSV unificados.
