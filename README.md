# Balanço Mensal do SIN

Aplicação Streamlit para transformar arquivos horários de **Balanço de Energia
por Subsistema**, disponibilizados pelo ONS, em uma tabela histórica com as
médias mensais do Sistema Interligado Nacional (SIN).

## O que a aplicação faz

- permite selecionar o ano inicial e o ano final da análise;
- baixa automaticamente cada ano no portal oficial de Dados Abertos do ONS;
- prioriza o formato Parquet e usa o CSV oficial como alternativa;
- mantém os downloads em cache por seis horas para agilizar novas consultas;
- seleciona apenas os registros identificados como `SIN`;
- calcula a média mensal de cada coluna de balanço;
- informa horas disponíveis, horas esperadas e cobertura de cada mês;
- compara os anos em gráfico;
- exporta para CSV somente ano, mês, gerações, carga e intercâmbio, em formato
  compatível com Excel em português.

Fonte oficial:

<https://dados.ons.org.br/dataset/balanco-energia-subsistema>

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

1. Extraia o ZIP.
2. Crie um repositório vazio no GitHub.
3. Envie **todo o conteúdo extraído de uma só vez**, incluindo `.streamlit`.
   O arquivo `app.py` precisa ficar diretamente na raiz do repositório, ao
   lado de `balanco_ons.py` e `requirements.txt`.
4. Confira se a raiz do GitHub contém:

```text
app.py
balanco_ons.py
requirements.txt
README.md
.streamlit/
```

5. Acesse o Streamlit Community Cloud e escolha **Create app**.
6. Selecione o repositório, a branch `main` e o arquivo principal `app.py`.
7. Em **Advanced settings**, mantenha ou selecione Python 3.12.
8. Clique em **Deploy**.

Não é necessário enviar dados ao GitHub. A própria aplicação consulta os
arquivos anuais do ONS e os processa em memória.

## Cálculo

Para cada ano e mês, a aplicação aplica:

```text
média mensal = soma dos valores horários válidos / quantidade de horários válidos
```

A consolidação usa diretamente a linha do ONS identificada como SIN. Os quatro
subsistemas regionais não são somados, o que evita distorções nos valores de
intercâmbio.

O ano corrente pode estar incompleto. A aplicação utiliza somente os horários
publicados pelo ONS até o momento da consulta e informa a cobertura de cada mês.

Um mês é marcado como **Parcial** quando possui menos registros horários do que
o total de horas de seu calendário. Essa marcação não impede o cálculo: a média
é feita com todos os valores válidos disponíveis.

Os arquivos do ONS passam por consistência recorrente e podem ser atualizados
após a publicação. O cache da aplicação expira em seis horas para permitir a
atualização periódica sem repetir downloads desnecessários.

## Testes

```bash
python -m unittest discover -s tests -v
```

Os mesmos testes são executados automaticamente pelo GitHub Actions em cada
`push` ou `pull request`.
