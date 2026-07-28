# Balanço Mensal do SIN

Aplicação Streamlit que consulta o Portal de Dados Abertos do ONS e transforma
os arquivos horários de **Balanço de Energia por Subsistema** em uma tabela
histórica com as médias mensais do Sistema Interligado Nacional (SIN).

## Fluxo automático

1. O usuário escolhe o ano inicial e o ano final.
2. Ao clicar em **Baixar dados do ONS**, a aplicação consulta a página oficial
   do conjunto de dados.
3. O código identifica por web scraping os links anuais em formato Parquet.
4. Os arquivos correspondentes ao período são baixados para uma pasta
   temporária.
5. A aplicação valida, consolida e guarda somente o resultado processado na
   sessão do Streamlit.
6. A pasta temporária e os Parquet são eliminados automaticamente.

Não é necessário baixar ou carregar arquivos manualmente.

Fonte consultada:

```text
https://dados.ons.org.br/dataset/balanco-energia-subsistema
```

## Processamento

- valida o ano do recurso contra as datas internas;
- seleciona apenas os registros identificados como `SIN`;
- converte datas e valores numéricos;
- descarta registros inválidos;
- evita contagem dupla quando há horários repetidos;
- calcula a média mensal de cada coluna de balanço;
- informa horas disponíveis, horas esperadas e cobertura de cada mês;
- compara anos em gráfico;
- exporta o resultado em CSV compatível com Excel em português.

As colunas conhecidas são apresentadas com nomes amigáveis:

| Coluna do ONS | Saída |
| --- | --- |
| `val_gerhidraulica` | Geração hidráulica (MWmed) |
| `val_gertermica` | Geração térmica (MWmed) |
| `val_gereolica` | Geração eólica (MWmed) |
| `val_gersolar` | Geração solar (MWmed) |
| `val_carga` | Carga (MWmed) |
| `val_intercambio` | Intercâmbio (MWmed) |

Outras colunas iniciadas por `val_` também são consolidadas automaticamente na
tabela e no gráfico.

## Regra de cálculo

Para cada ano e mês:

```text
média mensal = soma dos valores horários válidos / quantidade de valores válidos
```

A consolidação usa diretamente a linha identificada como `SIN`. Os quatro
subsistemas regionais não são somados, evitando distorções nos valores de
intercâmbio.

Um mês é marcado como **Parcial** quando possui menos registros horários que o
total de horas de seu calendário. A média continua sendo calculada com os
valores válidos disponíveis.

## Executar localmente

Requer Python 3.10 ou superior e acesso à internet.

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
streamlit run app.py
```

### Linux ou macOS

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## Publicar no Streamlit Community Cloud

1. Envie os arquivos do projeto para um repositório GitHub.
2. No Streamlit Community Cloud, escolha **Create app**.
3. Selecione o repositório, a branch `main` e o arquivo `app.py`.
4. Em **Advanced settings**, selecione Python 3.12.
5. Clique em **Deploy**.

O servidor onde a aplicação for publicada precisa permitir conexões HTTPS com:

- `dados.ons.org.br`;
- `ons-aws-prod-opendata.s3.amazonaws.com`.

## Estrutura

- `app.py`: interface e estado da sessão;
- `ons_download.py`: scraping, download e validação dos Parquet;
- `balanco_ons.py`: limpeza e consolidação mensal;
- `tests/`: testes automatizados.

## Testes

```bash
python -m unittest discover -s tests -v
```
