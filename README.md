# Dados Mensais ONS — Balanço + EAR + ENA + sistema.dat

Aplicação Streamlit unificada para baixar e analisar três bases oficiais do ONS:

- **Balanço Energético por Subsistema**;
- **Energia Armazenada (EAR) diária por Subsistema**;
- **Energia Natural Afluente (ENA) diária por Subsistema**.

Também permite carregar qualquer nova versão do **`sistema.dat` do NEWAVE**. O
arquivo é lido diretamente no navegador da aplicação; nenhum ano, mês ou linha
do exemplo fica fixado no código.

## Nova base: Geração Térmica por Motivo de Despacho

A quarta opção **Térmicas** consulta o catálogo oficial [ONS Dados Abertos](https://dados.ons.org.br/dataset/geracao-termica-despacho-2). É carregada **somente quando selecionada** antes de clicar em *Baixar dados do ONS*, pois pode conter muitos arquivos. Mantém-se independente da tabela unificada de Balanço/EAR/ENA para evitar dupla contagem.

- 2013–2021: arquivo anual; 2022 em diante: arquivos mensais (meses publicados);
- prioridade Parquet, com fallback CSV e validação de origem/conteúdo;
- filtros de data, subsistema, usina, combustível e patamar;
- seleção de geração programada/verificada/despachada e motivos de despacho (colunas originais);
- curva temporal horária, média diária, média mensal ou média anual e ranking de usinas;
- tabela de médias por período, registros originais com todas as colunas e CSV;
- exportação integral dos dados filtrados em CSV comprimido (.csv.gz) para conjuntos grandes;
- painel de arquivos efetivamente processados, com erros por recurso.

**Definição das médias:** primeiro somam-se as usinas por instante horário; depois calcula-se a média aritmética das horas observadas no período. Isso representa a potência média do grupo de usinas e evita médias indevidas por número de linhas. Dados ausentes não são preenchidos artificialmente com zeros. A média pode ficar parcial se faltarem horas. Motivos de despacho **não são aditivos entre si**, porque algumas classificações são sobrepostas. Geração programada e verificada também não devem ser somadas.

Para downloads térmicos, recomenda-se começar com um ou dois anos: os arquivos são mais volumosos que EAR/ENA. A seleção de bases e a seleção das grandezas exibidas são independentes.

## Funcionamento

1. Opcionalmente, carregue um `sistema.dat`. A análise NEWAVE aparece imediatamente, sem depender do download das bases do ONS.
2. Selecione o intervalo de anos.
3. Clique em **Baixar dados do ONS**. A aplicação processa **Balanço, EAR e ENA em paralelo**, cada base em uma pasta temporária independente. Dentro de cada base, os anos permanecem sequenciais para limitar as conexões simultâneas com o portal. Para ENA, prioriza Parquet e usa automaticamente o CSV oficial quando o Parquet do ano não existe ou falha.
4. No seletor segmentado entre o painel de período e o painel de resultados, marque **Balanço**, **EAR**, **ENA** ou qualquer combinação entre elas.
5. Escolha o subsistema e a discretização: **diária**, **mensal** ou **anual**.
6. Visualize os dados em uma única tabela com vírgula decimal e baixe um único CSV no padrão regional: separador `;` entre colunas e decimal `,`. As colunas auxiliares de cobertura e status permanecem na tabela, mas não são exportadas.
7. No **Painel de gráficos**, navegue por abas:
   - **Painel 1**: exploração independente de Balanço, EAR e ENA, com seleção de grandeza e exportação SVG;
   - **Painel 2**: carga e curva de pato configurável (`Carga − Solar` ou `Carga − Eólica − Solar`) e composição empilhada com ordem livre das fontes hidráulica, térmica, eólica e solar. O painel usa cores pastel e pode ser exportado em SVG.
8. Consulte **Arquivos processados** no último painel da página.

## Análise automática do sistema.dat

O parser usa os campos mensais fixos definidos pelo formato do NEWAVE para
descobrir quais meses estão realmente preenchidos em cada ano. Assim, um deck
que comece em fevereiro, maio, setembro ou em qualquer outro mês é posicionado
corretamente no eixo temporal. Também são descobertos os blocos e pares que
existem naquele arquivo, sem depender dos números de linha da amostra.

A interface apresenta:

- mercado total do SIN e carga global, definida como `Mercado SIN + MMGD total`;
- PCH, PCT, eólica e solar centrais, além de MMGD total, eólica MMGD e solar MMGD;
- horizonte, quantidade de meses, pico de carga, crescimento do mercado e participação final da MMGD;
- limites de intercâmbio nos dois sentidos, tratando `99.999` como marcador não restritivo;
- custo de déficit, mercado e geração por subsistema no mês escolhido;
- exportações CSV da série agregada e dos blocos extraídos.

A tabela e o CSV continuam em discretização diária, mensal ou anual. O painel de gráficos também oferece a opção **horária**, aplicada exclusivamente ao Balanço, que possui série nessa resolução. Ao selecionar a visualização horária, os cartões de EAR e ENA não são exibidos.

A configuração dos gráficos é separada da configuração da tabela. Alterar um gráfico não refaz o download e não modifica o CSV: a visualização é recalculada a partir dos dados que já estão na sessão. O Painel 1 mantém a configuração à esquerda e as curvas sincronizadas à direita. O Painel 2 possui estado próprio de subsistema, discretização e datas; permite escolher a ordem das quatro áreas empilhadas, incluir ou excluir a eólica da curva de pato e baixar a composição em SVG. Na discretização horária, o eixo temporal mostra também as horas. No gráfico de composição, a linha da carga permanece sobre as áreas empilhadas. Para subsistemas individuais, diferenças entre a carga e a soma das fontes podem refletir o intercâmbio.

### Grandezas de ENA

- ENA bruta em MWmed;
- ENA bruta em percentual da Média de Longo Termo (% MLT);
- ENA armazenável em MWmed;
- ENA armazenável em percentual da Média de Longo Termo (% MLT).

Quando o arquivo não contém uma linha própria para o SIN, a aplicação só gera a série calculada nos dias em que SE/CO, Sul, Nordeste e Norte estão simultaneamente disponíveis. Para cada subsistema, reconstrói-se a MLT implícita por `MLT_i = ENA_i / (%MLT_i / 100)`; em seguida, calcula-se `%MLT_SIN = 100 × ΣENA_i / ΣMLT_i`. A interface identifica a opção como **SIN · ENA calculada**. Se faltar qualquer um dos quatro subsistemas, não é criado valor do SIN para aquele dia.

## Execução local

No Windows, dê duplo clique em `iniciar_dadosmensaisons_v10.bat`. Na primeira
execução ele cria um ambiente isolado para esta versão e instala as dependências.

Ou execute manualmente:

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
- `sistema_dat.py`: leitura estrutural, validação e agregação dinâmica do `sistema.dat` do NEWAVE.
