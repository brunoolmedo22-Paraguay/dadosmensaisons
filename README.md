# Balanço Mensal do SIN

Aplicação Streamlit que baixa sozinha os arquivos horários de **Balanço de
Energia por Subsistema** do Portal de Dados Abertos do ONS e os transforma em
uma tabela histórica com as médias mensais do Sistema Interligado Nacional
(SIN).

## Origem dos dados

<https://dados.ons.org.br/dataset/balanco-energia-subsistema>

A lista de arquivos é obtida pela API CKAN do portal:

```text
https://dados.ons.org.br/api/3/action/package_show?id=balanco-energia-subsistema
```

Quando a API está indisponível, a aplicação recorre ao padrão público de
endereços do ONS:

```text
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_<ANO>.parquet
```

## O que a aplicação faz

- baixa os arquivos anuais do intervalo escolhido para uma pasta temporária;
- prefere Parquet e cai para CSV automaticamente quando o ano não tem Parquet;
- reaproveita o que já está na pasta temporária, sem baixar de novo;
- aceita também o envio manual de arquivos, como alternativa;
- lê o ano diretamente do nome de cada arquivo;
- valida o ano do nome contra as datas internas;
- seleciona apenas os registros identificados como `SIN`;
- calcula a média mensal de cada coluna de balanço;
- informa horas disponíveis, horas esperadas e cobertura de cada mês;
- evita contagem dupla quando dois arquivos possuem o mesmo horário;
- compara os anos em gráfico;
- exporta para CSV somente ano, mês, gerações, carga e intercâmbio, em formato
  compatível com Excel em português.

## Como usar

1. escolha o **intervalo de anos** na barra lateral, por exemplo 2022 a 2026;
2. clique em **Baixar dados abertos**;
3. acompanhe a barra de progresso; ao final a tabela mensal aparece pronta.

Os arquivos ficam em `<pasta temporária do sistema>/ons_balanco_energia_subsistema`.
No Streamlit Community Cloud essa pasta é apagada a cada reinício do contêiner,
o que é esperado: basta clicar em baixar novamente.

O nome de cada arquivo deve conter um único ano:

```text
BALANCO_ENERGIA_SUBSISTEMA_2026.parquet
```

## Formatos aceitos

`.parquet`, `.csv`, `.xlsx`, `.xlsm` e `.xls`. O separador do CSV é detectado
automaticamente, assim como vírgula ou ponto como separador decimal.

## Estrutura esperada do arquivo

A aplicação procura automaticamente a tabela que contenha:

- `din_instante`;
- `id_subsistema` ou `nom_subsistema`;
- uma ou mais colunas de valores iniciadas por `val_`.

As colunas conhecidas são apresentadas com nomes amigáveis:

| Coluna do ONS | Saída |
| --- | --- |
| `val_gerhidraulica` | Geração hidráulica (MWmed) |
| `val_gertermica` | Geração térmica (MWmed) |
| `val_gereolica` | Geração eólica (MWmed) |
| `val_gersolar` | Geração solar (MWmed) |
| `val_carga` | Carga (MWmed) |
| `val_intercambio` | Intercâmbio (MWmed) |

Outras colunas iniciadas por `val_` também são consolidadas automaticamente.

## Executar localmente

Requer Python 3.10 ou superior.

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

## Publicar pelo GitHub no Streamlit Community Cloud

1. Crie um repositório vazio no GitHub.
2. Envie todos os arquivos e pastas deste projeto, incluindo `.streamlit`.
3. Acesse o Streamlit Community Cloud e escolha **Create app**.
4. Selecione o repositório, a branch `main` e o arquivo principal `app.py`.
5. Em **Advanced settings**, mantenha ou selecione Python 3.12.
6. Clique em **Deploy**.

Não é necessário enviar arquivos de dados ao GitHub. Eles são baixados do
portal do ONS em tempo de execução.

## Cálculo

Para cada ano e mês, a aplicação aplica:

```text
média mensal = soma dos valores horários válidos / quantidade de horários válidos
```

A consolidação usa diretamente a linha do ONS identificada como SIN. Os quatro
subsistemas regionais não são somados, o que evita distorções nos valores de
intercâmbio.

Um mês é marcado como **Parcial** quando possui menos registros horários do que
o total de horas de seu calendário. Essa marcação não impede o cálculo: a média
é feita com todos os valores válidos disponíveis.

## Testes

```bash
python -m unittest discover -s tests -v
```

Os mesmos testes são executados automaticamente pelo GitHub Actions em cada
`push` ou `pull request`.
