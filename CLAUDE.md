# Como Vota Deputado? — contexto para o Claude Code

Bot que publica no Instagram (e prepara para o TikTok) como deputados e senadores votaram no Plenário, com dados oficiais da Câmara e do Senado. Inclui também um site com o teste "Quem vota como você?". Este arquivo existe para quem continuar o projeto, pessoa ou IA, não precisar redescobrir as decisões.

**Idioma:** todo o código, os nomes, os comentários, os textos e as mensagens são em **português do Brasil**. Mantenha assim.

## Regras de produto (não quebrar)

1. **Neutralidade.** O perfil nunca opina sobre o mérito de um voto, de um partido ou de um político. Os textos usam a ementa oficial, sem adjetivos de valor. Os ganchos dos formatos passam pela lista `PROIBIDOS` em `bot/formatos.py`, e o prompt da IA em `bot/summarizer.py` proíbe opinião.
1b. **Linguagem simples e inclusiva.** O público é geral: frases curtas, palavras do dia a dia e números concretos ("mais da metade dos 513 deputados", não "maioria absoluta"). Termo técnico só quando for inevitável, e explicado na hora ("relator: o deputado encarregado de analisar o projeto"). A ementa oficial aparece sempre, mas nunca sozinha: o slide "O que está em votação" explica o tipo de projeto e a etapa.
2. **Só dados oficiais e verificáveis.** Toda legenda tem o link da fonte. Só entram votações **nominais**: as simbólicas e secretas não têm voto individual e são descartadas.
3. **Nada é publicado sem aprovação humana** no Telegram.
4. **Identidade visual:** o Guia de Marca v1.0 está aplicado nos templates.
   - Cores: azul `#0E2233`, amarelo `#FFC93C`, verde SIM `#1FA97A`, vermelho NÃO `#E4433C`, cinza `#8A94A0`, off-white `#F6F3EC`.
   - Fontes embutidas em `bot/render/fonts/`: Archivo Black, Inter e IBM Plex Mono.
   - Ícones ✓ ✕ — em SVG, **nunca emoji para representar voto**.
5. **Ausência ≠ falta.** Sem registro de voto, o texto é "NÃO VOTOU", nunca "faltou": pode ser licença ou missão oficial.
6. **Demos sempre fictícias**, com marca d'água "EXEMPLO FICTÍCIO". Nunca invente voto de parlamentar real.
7. **Escolhas que poderiam parecer perseguição são automáticas e explicadas:** o Voto da Semana usa rodízio, e a seleção de votações usa regras públicas em `bot/selector.py`.

## Arquitetura

```
main.py                     CLI com todos os comandos (argparse)
bot/models.py               Votacao, Voto, normalização, placar, quorum() de PEC/PLP
bot/collectors/camara.py    API Dados Abertos da Câmara (coletar, coletar_por_id)
bot/collectors/senado.py    API Dados Abertos do Senado (totais_oficiais incluídos)
bot/selector.py             pontua e escolhe as votações relevantes
bot/summarizer.py           título, resumo (IA opcional) e legenda; apelido vira o título
apelidos.yaml               apelidos de projetos cadastrados pelo dono (vale mais que o do Senado)
bot/qualidade.py            alertas de consistência antes da aprovação
bot/entenda.py              slide "O que está em votação": tipo de projeto e etapa (substitutivo, destaque...)
bot/formatos.py + formatos/ biblioteca de formatos (YAML), rodízio, peso por desempenho
bot/render/renderer.py      HTML (Jinja) → JPEG via Playwright; mapa em grade (GRADE_UF)
bot/render/templates/       carrossel, explicador, voto_semana, fixados, _cta_teste, logo.svg
bot/semana.py               Voto da Semana (rodízio de parlamentar)
bot/frias.py + pautas_frias/  pautas frias: explicadores YAML, Bancada do Estado, repost
bot/cta.py                  slide e linha de chamada para o teste do site (SITE_TESTE_URL)
bot/agenda.py               fila de publicação em horários (HORARIOS_PUBLICACAO)
bot/approval.py             Telegram: envio com botões, leitura de cliques e comandos
bot/publisher.py            Instagram Graph API (carrossel, imagem única, insights)
bot/token_ig.py             confere e renova o token do Instagram
bot/metricas.py             coleta de métricas e pontuação
bot/relatorio.py            relatório semanal
bot/diagnostico.py          checagem da configuração
bot/tiktok.py               versão 9:16 e legenda do TikTok
bot/tiktok_api.py           Content Posting API (modos manual/rascunho/direto)
bot/quiz.py + quiz/ + site/ teste "Quem vota como você?" (GitHub Pages)
bot/storage.py              rascunhos em data/drafts/<id>/meta.json e data/state.json
scripts/midia.sh            imagens no branch `midia`, sem histórico
contador/worker.js          contador anônimo do teste (Cloudflare Worker, opcional)
tests/test_pipeline.py      testes offline (APIs simuladas)
```

### Fluxo de um post
1. `gerar` (todo dia, 8h47 BRT) coleta os últimos 3 dias, deduplica, seleciona até `MAX_POSTS`, escolhe o formato, renderiza, roda a checagem de qualidade, gera a versão TikTok e manda para o Telegram.
2. Sem votação há `DIAS_SEM_POST_PARA_FRIA` dias, gera uma pauta fria, em rodízio explicador → bancada → repost.
3. `verificar` (a cada 15 min) lê os cliques:
   - **Aprovar** agenda no próximo horário livre.
   - **Agora** publica na hora.
   - Os comandos são `/fila`, `/legenda <id>`, `/agora <id>`, `/aprovar <id>` e `/descartar <id>`.
4. Quando o horário chega, publica no Instagram e depois no TikTok (API ou pacote manual no Telegram).
5. `metricas` (todo dia) cuida do token do Instagram, coleta insights e manda o relatório nas segundas.

### Status de um rascunho
`gerado → enviado → agendado → aprovado → publicado`, ou `descartado` / `erro`. O status fica em `meta.json` e é espelhado em `state.json["rascunhos"]`. Use sempre `storage.atualizar_status()`, que também grava o histórico.

### Onde fica o estado
- `data/state.json`: offset do Telegram, status, uso de formatos, rodízios, reposts, seguidores e token do Instagram.
- `data/drafts/<id>/meta.json`: votação completa, textos, formato, alertas, métricas e TikTok.
- **As imagens não vão para o branch principal** (`.gitignore`). Elas ficam no branch `midia`, recriado com um único commit por `scripts/midia.sh`. Os workflows rodam `restaurar` antes e `publicar` depois.

## Comandos

```
python main.py demo [--modelo carrossel|semana|fria] [--formato <id>] [--bancada]   # visual, sem internet
python main.py gerar [--sem-telegram] [--inicio AAAA-MM-DD --fim AAAA-MM-DD]
python main.py refazer <id> [<id>...] [--sem-telegram]   # refaz rascunhos não aprovados (workflow Gerar: campo "refazer")
python main.py verificar | semana | fria [--arquivo|--uf] | repost | metricas
python main.py formatos | relatorio | diagnostico [--telegram] | token-instagram
python main.py quiz [--demo] | fixados | tiktok-login [--codigo] | midia-site | midia-branch
python tests/test_pipeline.py          # testes (precisam de Chromium só nos renders)
```

Ambiente local: `pip install -r requirements.txt` e `python -m playwright install chromium`. Copie o `.env.example` para `.env`.

## Workflows (`.github/workflows/`)
| Arquivo | Quando | Faz |
|---|---|---|
| `gerar-diario.yml` | diário 8h47 BRT | rascunhos, pauta fria, branch midia, dispara o site se o TikTok estiver em modo API |
| `verificar.yml` | a cada 15 min | cliques do Telegram, fila, Instagram, TikTok, salva o token do TikTok |
| `voto-da-semana.yml` | sábado 10h47 | Voto da Semana |
| `metricas.yml` | diário 5h47 | token do Instagram, métricas, relatório (segundas) |
| `site.yml` | push em site/quiz, segundas, sob demanda | `quiz.json` e mídia 9:16 → GitHub Pages |
| `diagnostico.yml` | manual | confere toda a configuração |

Todos os que gravam estado usam `concurrency: como-vota-estado`, para nunca rodarem juntos, e fazem `git pull --rebase` antes do push. Nomes de passo com dois-pontos **precisam de aspas** no YAML: isso já quebrou o `verificar.yml` uma vez.

## O que NÃO foi validado de verdade (prioridade ao continuar)

O projeto foi construído num ambiente sem acesso às APIs. Tudo foi testado com respostas simuladas, que seguem a documentação oficial. Na primeira execução real, confira:

1. **APIs do Congresso:** o formato real de `/votacoes`, `/votos` e `/orientacoes` da Câmara, e o JSON de `/dadosabertos/votacao` do Senado: nomes de campo, valores de `siglaVotoParlamentar` e se `codigoSessaoVotacao` é estável. Ajuste em `bot/collectors/`.
2. **Instagram:**
   - publicação de carrossel;
   - nomes das métricas em `insights` (há uma lista de reserva em `publisher.CONJUNTOS_METRICAS`);
   - `content_publishing_limit`;
   - renovação do token (`graph.instagram.com/refresh_access_token`).
3. **Telegram:** `sendMediaGroup` com documentos (pacote TikTok) e os limites de tamanho.
4. **TikTok:** o fluxo OAuth, o `MEDIA_UPLOAD` de fotos e a verificação de domínio. Sem auditoria, o modo `direto` só posta em conta privada, e as diretrizes do TikTok não aceitam ferramenta para contas próprias. **O modo recomendado é `rascunho`.**
5. **`scripts/midia.sh` no GitHub Actions:** foi testado com um remoto Git local, não no GitHub.
6. **Formato real das ementas e descrições:** afeta o seletor (`PENALIDADES`/`BONUS`) e a regra de quórum (`_FORA_DO_QUORUM`).

Rode `python main.py diagnostico` e o workflow *Diagnóstico* antes de tudo, e mantenha `DRY_RUN=1` nas primeiras semanas.

## Decisões tomadas (e por quê)

- **GitHub Actions + arquivos no repositório**, em vez de servidor e banco: custo zero e histórico auditável. As imagens públicas saem do `raw.githubusercontent.com` (repositório público, branch `midia`).
- **Aprovação humana obrigatória**, pelo risco reputacional de conteúdo político.
- **Fila de horários** (11h45 e 18h45 por padrão), com o botão **Agora** para notícias urgentes.
- **Rodízio de formatos até 3 posts medidos por formato** e depois sorteio com peso pela pontuação, que é (3×salvos + 3×compart. + comentários + 0,5×curtidas) / alcance × 1000.
- **Repost só de explicadores** que estejam entre os 30% melhores, com pelo menos 4 medidos e pelo menos 60 dias desde a última vez. Votações envelhecem e não voltam.
- **Quórum:** PEC 308/49 e PLP 257/41, mostrado no placar. Destaques e requerimentos ficam de fora.
- **Mapa por estado em grade** (`GRADE_UF`), não geográfico: estados pequenos ficam visíveis. É um formato do rodízio, não fixo (decisão do dono).
- **Apelido do projeto como título** ("Fim da escala 6x1"): vem do campo `apelido` da API do Senado (`/processo`), também para projetos da Câmara a partir de 2019, porque a numeração é única. O `apelidos.yaml` permite cadastrar ou trocar um apelido. Todo post com apelido gera um alerta para conferir a neutralidade: apelido criado por um dos lados ("PEC da Blindagem") não entra.
- **Marca por Casa:** o perfil se chama "Como Vota Deputado?", mas os posts de votação do Senado se assinam "Como Vota Senador?" (topo dos slides, slide do teste e logo do final). Explicadores, fixados e hashtag #ComoVotaDeputado não mudam (decisão do dono).
- **Dois símbolos, de propósito:** o avatar (`assets/avatar.png`) é o Congresso estilizado com ✓ e ✕, e a cédula do `logo.svg` continua dentro dos posts. Não unificar (decisão do dono).
- **"Link na bio"** foi tirado dos posts até o site existir. Hoje ele só aparece no slide do teste, que só liga com `SITE_TESTE_URL`.
- **Teste do site:** o cálculo roda no navegador, sem rastreadores. O contador opcional guarda só totais anônimos (LGPD). Antes de lançar, vale revisão jurídica (LGPD e lei eleitoral). Evite publicar estatísticas do teste em período de campanha.
- **Várias contas:** só com identidade própria e transparente (ex.: um perfil por estado). Nada de rede de perfis que fingem ser independentes, pelo risco de "comportamento inautêntico coordenado".
- **Pesquisa de virais:** é feita fora do bot, pelo dono, no Codex. O bot só guarda a **estrutura** em `formatos/`, nunca conteúdo de terceiros. Raspar plataformas está fora de questão.

## Estado atual e próximos passos

**Pronto:** tudo o que está acima, com os testes passando (`python tests/test_pipeline.py`).

**O dono ainda precisa:**
- configurar Telegram, Instagram, `GH_PAT`, secrets e variables (passo a passo no README, seção "Colocar no ar");
- publicar os 3 posts fixados;
- preencher `quiz/perguntas.yaml` com votações reais. O `site/quiz.json` atual é **fictício** (`"demo": true`), e o diagnóstico acusa isso se o site for ao ar assim.

**Ideias já discutidas e não feitas:**
- integração com um intermediário auditado do TikTok para postagem pública 100% automática (ex.: Upload-Post), pendente de decisão e da leitura da documentação deles;
- agenda da semana (o que o Congresso vai votar), usando a API de eventos/pauta;
- Stories com enquete (a API não publica figurinhas: o bot geraria a arte e o dono postaria);
- página com a lista completa de votos por parlamentar (semente do SaaS) e volta do "link na bio";
- fidelidade partidária mensal, comparativo Câmara × Senado, "neste dia";
- presença e gastos da cota parlamentar: sensíveis, só com muito cuidado de tom;
- legislatura nova em fevereiro de 2027: o teste e o Voto da Semana vão precisar lidar com a troca de parlamentares.

## Convenções de código
- Funções e variáveis em português, sem acento nos identificadores (`gerar_textos`, `votacao`, `pautas_frias`).
- Falhas em partes acessórias (IA, TikTok, métricas) **não podem derrubar o pipeline principal**: registre no log, avise no Telegram e siga em frente.
- Toda chamada externa tem timeout. Testes usam objetos falsos (`_FakeTikTok`, monkeypatch de `_get`, `_post`, `_http`).
- Ao mudar layout, renderize com `python main.py demo ...` e **olhe a imagem** antes de entregar.
