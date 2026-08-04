# Dados Mensais ONS — Balanço + EAR + ENA

Aplicação Streamlit unificada para baixar e analisar três bases oficiais do ONS:

- **Balanço Energético por Subsistema**;
- **Energia Armazenada (EAR) diária por Subsistema**;
- **Energia Natural Afluente (ENA) diária por Subsistema**.

## Funcionamento

1. Selecione o intervalo de anos.
2. Clique em **Baixar dados do ONS**. A aplicação processa **Balanço, EAR e ENA em paralelo**, cada base em uma pasta temporária independente. Dentro de cada base, os anos permanecem sequenciais para limitar as conexões simultâneas com o portal. Para ENA, prioriza Parquet e usa automaticamente o CSV oficial quando o Parquet do ano não existe ou falha.
3. No seletor segmentado entre o painel de período e o painel de resultados, marque **Balanço**, **EAR**, **ENA** ou qualquer combinação entre elas.
4. Escolha o subsistema e a discretização: **diária**, **mensal** ou **anual**.
5. Visualize os dados em uma única tabela com vírgula decimal e baixe um único CSV no padrão regional: separador `;` entre colunas e decimal `,`. As colunas auxiliares de cobertura e status permanecem na tabela, mas não são exportadas.
6. No **Painel de gráficos**, navegue por abas:
   - **Painel 1**: exploração independente de Balanço, EAR e ENA, com seleção de grandeza e exportação SVG;
   - **Painel 2**: carga e curva de pato configurável (`Carga − Solar` ou `Carga − Eólica − Solar`) e composição empilhada com ordem livre das fontes hidráulica, térmica, eólica e solar. O painel usa cores pastel e pode ser exportado em SVG.
7. Consulte **Arquivos processados** no último painel da página.

A tabela e o CSV continuam em discretização diária, mensal ou anual. O painel de gráficos também oferece a opção **horária**, aplicada exclusivamente ao Balanço, que possui série nessa resolução. Ao selecionar a visualização horária, os cartões de EAR e ENA não são exibidos.

A configuração dos gráficos é separada da configuração da tabela. Alterar um gráfico não refaz o download e não modifica o CSV: a visualização é recalculada a partir dos dados que já estão na sessão. O Painel 1 mantém a configuração à esquerda e as curvas sincronizadas à direita. O Painel 2 possui estado próprio de subsistema, discretização e datas; permite escolher a ordem das quatro áreas empilhadas, incluir ou excluir a eólica da curva de pato e baixar a composição em SVG. Na discretização horária, o eixo temporal mostra também as horas. No gráfico de composição, a linha da carga permanece sobre as áreas empilhadas. Para subsistemas individuais, diferenças entre a carga e a soma das fontes podem refletir o intercâmbio.

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
- `unified_ons.py`: junção temporal, tabela e CSV unificados;
- `parallel_ons.py`: orquestração concorrente e isolada das três bases, com eventos de progresso entregues à thread principal do Streamlit.
- `power_panel.py`: preparação da curva de pato e da composição de geração exibidas no Painel 2.
