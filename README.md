# Dados Mensais ONS — Balanço + EAR + ENA

Aplicação Streamlit unificada para baixar e analisar três bases oficiais do ONS:

- **Balanço Energético por Subsistema**;
- **Energia Armazenada (EAR) diária por Subsistema**;
- **Energia Natural Afluente (ENA) diária por Subsistema**.

## Funcionamento

1. Selecione o intervalo de anos.
2. Clique em **Baixar dados do ONS**. A aplicação localiza, baixa e valida os arquivos anuais das três bases. Para ENA, prioriza Parquet e usa automaticamente o CSV oficial quando o Parquet do ano não existe ou falha.
3. No seletor segmentado entre o painel de período e o painel de resultados, marque **Balanço**, **EAR**, **ENA** ou qualquer combinação entre elas.
4. Escolha o subsistema e a discretização: **diária**, **mensal** ou **anual**.
5. Visualize os dados em uma única tabela e baixe um único CSV. As colunas auxiliares de cobertura e status permanecem na tabela, mas não são exportadas.
6. No **Painel de gráficos**, escolha de forma independente o subsistema, a discretização e o intervalo. A aplicação mostra um gráfico para cada base compatível marcada no seletor superior e oferece download individual em SVG.
7. Consulte **Arquivos processados** no último painel da página.

A tabela e o CSV continuam em discretização diária, mensal ou anual. O painel de gráficos também oferece a opção **horária**, aplicada exclusivamente ao Balanço, que possui série nessa resolução. Ao selecionar a visualização horária, os cartões de EAR e ENA não são exibidos.

A configuração dos gráficos é separada da configuração da tabela. Alterar um gráfico não refaz o download e não modifica o CSV: a visualização é recalculada a partir dos dados que já estão na sessão. O arranjo compacto é uma grade 2 × 2, com a configuração na primeira célula e até três gráficos — Balanço, EAR e ENA — nas demais. Em cada cartão, o seletor de grandeza e o botão de download SVG ficam na mesma linha.

### Grandezas de ENA

- ENA bruta em MWmed;
- ENA bruta em percentual da Média de Longo Termo (% MLT);
- ENA armazenável em MWmed;
- ENA armazenável em percentual da Média de Longo Termo (% MLT).

Quando o arquivo não contém uma linha própria para o SIN, a aplicação só gera a série calculada nos dias em que SE/CO, Sul, Nordeste e Norte estão simultaneamente disponíveis. Para cada subsistema, reconstrói-se a MLT implícita por `MLT_i = ENA_i / (%MLT_i / 100)`; em seguida, calcula-se `%MLT_SIN = 100 × ΣENA_i / ΣMLT_i`. A interface identifica a opção como **SIN · ENA calculada**. Se faltar qualquer um dos quatro subsistemas, não é criado valor do SIN para aquele dia.

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
- `ena_processing.py`: processamento unificado dos arquivos CSV e Parquet de ENA;
- `ena_download.py`: download da ENA com preferência por Parquet e fallback automático para CSV;
- `unified_ons.py`: junção temporal, tabela e CSV unificados.
