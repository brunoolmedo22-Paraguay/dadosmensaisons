# Balanço Mensal do SIN

Aplicação Streamlit para transformar arquivos horários de **Balanço de Energia
por Subsistema**, disponibilizados pelo ONS, em uma tabela histórica com as
médias mensais do Sistema Interligado Nacional (SIN).

## O que a aplicação faz

- recebe vários arquivos Excel ao mesmo tempo;
- lê o ano diretamente do nome de cada arquivo;
- valida o ano do nome contra as datas internas;
- seleciona apenas os registros identificados como `SIN`;
- calcula a média mensal de cada coluna de balanço;
- informa horas disponíveis, horas esperadas e cobertura de cada mês;
- evita contagem dupla quando dois arquivos possuem o mesmo horário;
- apresenta quatro gráficos de variação mensal, um por fonte de geração;
- exporta os dados dos gráficos em CSV;
- exporta para CSV somente ano, mês, gerações, carga e intercâmbio, em formato
  compatível com Excel em português.
- exporta a mesma tabela simplificada em Excel formatado.

O arquivo deve conter um único ano no nome:

```text
BALANCO_ENERGIA_SUBSISTEMA_2026.xlsx
```

## Estrutura esperada do Excel

A aplicação procura automaticamente a planilha que contenha:

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

Não é necessário enviar os Excel ao GitHub. Eles são carregados pelo usuário
diretamente na interface e processados em memória.

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
