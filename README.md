# Como Vota — bot publicador

Todo dia o bot busca as votações nominais do Plenário da Câmara e do Senado, escolhe as mais relevantes e gera um carrossel por votação. Ele manda o carrossel para você aprovar no Telegram e, quando você aprova, publica no Instagram.

```
GitHub Actions (diário)           GitHub Actions (a cada 15 min)
┌───────────────────────┐         ┌──────────────────────────┐
│ coleta Câmara/Senado  │         │ lê cliques no Telegram   │
│ seleciona relevantes  │ ──────▶ │ aprovado? publica no IG  │
│ texto (ementa + IA)   │ Telegram│ descartado? arquiva      │
│ imagens 1080x1350     │  ✅ 🗑️  │ avisa o link do post     │
│ commit em data/       │         │ commit do status         │
└───────────────────────┘         └──────────────────────────┘
```

> Para continuar o desenvolvimento com o Claude Code, o contexto completo (arquitetura, decisões e pendências) está em `CLAUDE.md`.

## Estrutura

| Arquivo | O que faz |
|---|---|
| `bot/collectors/camara.py` | API Dados Abertos da Câmara: votações do Plenário, votos e orientações. Descarta votações simbólicas. |
| `bot/collectors/senado.py` | API Dados Abertos do Senado. Marca votações secretas, que o seletor descarta. |
| `bot/models.py` | Formato único `Votacao`/`Voto`, com placar, votos por partido e quem votou contra o partido. |
| `bot/selector.py` | Regras de relevância: tipo da proposição, penalidade para votos procedimentais, bônus para placar apertado. |
| `bot/summarizer.py` | Título, resumo e legenda. Usa a IA se houver `ANTHROPIC_API_KEY`; sem ela, usa a ementa oficial. |
| `bot/render/` | Template HTML que vira JPEG via Playwright. Slides: capa, placar, partidos, dissidentes e chamada final. |
| `bot/approval.py` | Envio para o Telegram com botões e leitura das decisões, sem servidor. |
| `bot/publisher.py` | Instagram Graph API: containers, carrossel e `media_publish`. |
| `bot/storage.py` | Rascunhos e estado em `data/`, versionados no Git. |
| `bot/formatos.py`, `formatos/` | Biblioteca de formatos validados e escolha por desempenho. |
| `bot/tiktok.py` | Versão 9:16 e legenda para o TikTok. |
| `bot/tiktok_api.py`, `site/tiktok-callback/` | Postagem pela API do TikTok (rascunho ou direto) e login. |
| `bot/metricas.py` | Métricas do Instagram e pontuação. |
| `bot/cta.py` | Chamada para o teste do site nos posts. |
| `bot/frias.py` | Pautas frias: fila de explicadores, Bancada do Estado e regra de dias sem post. |
| `pautas_frias/` | Explicadores em YAML (um arquivo = um carrossel). |
| `bot/semana.py` | Voto da Semana: pautas da semana, rodízio do parlamentar e legenda. |
| `bot/quiz.py`, `quiz/`, `site/` | Teste Quem vota como você: curadoria, exportador e página. |
| `contador/worker.js` | Contador anônimo agregado (opcional). |
| `bot/qualidade.py` | Checagem dos dados antes da aprovação. |
| `bot/agenda.py` | Fila de publicação em horários fixos. |
| `bot/token_ig.py` | Conferência e renovação do token do Instagram. |
| `bot/diagnostico.py` | Diagnóstico da configuração. |
| `bot/relatorio.py` | Relatório semanal no Telegram. |
| `scripts/midia.sh` | Imagens no branch `midia`, sem histórico. |
| `main.py` | Comandos `gerar`, `semana`, `fria`, `repost`, `metricas`, `formatos`, `tiktok-login`, `midia-site`, `token-instagram`, `diagnostico`, `relatorio`, `quiz`, `fixados`, `verificar`, `publicar ID` e `demo`. |

## Testar no seu computador

```bash
pip install -r requirements.txt
python -m playwright install chromium
python main.py demo                # gera um carrossel FICTÍCIO em data/drafts/camara-demo-0001
python tests/test_pipeline.py      # testes offline
python main.py gerar --sem-telegram   # dados reais da última semana, sem enviar nada
```

## Colocar no ar

### 1. Repositório
Crie um repositório **público** no GitHub e suba esta pasta. Ele precisa ser público porque a API do Instagram baixa as imagens por URL, e o `raw.githubusercontent.com` de um repositório público serve para isso. Se preferir repositório privado, troque `PUBLIC_BASE_URL` por um bucket público, como Cloudflare R2 ou S3, e suba as imagens nele.

### 2. Telegram
1. Fale com o **@BotFather**, use `/newbot` e copie o token.
2. Mande qualquer mensagem para o seu bot e abra `https://api.telegram.org/bot<TOKEN>/getUpdates` para descobrir o seu `chat.id`.

### 3. Instagram
1. Converta o perfil para **conta Profissional** (Creator ou Business).
2. Em developers.facebook.com, crie um app com o produto **Instagram** e adicione a sua conta.
3. Gere um token de longa duração com permissão de publicação de conteúdo e anote o **ID da conta do Instagram**.
4. O token de longa duração dura cerca de 60 dias. Renove antes de vencer.

### 4. Secrets e variables do GitHub
Configure em *Settings → Secrets and variables → Actions*.

**Secrets:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `IG_USER_ID`, `IG_ACCESS_TOKEN` e, opcionalmente, `ANTHROPIC_API_KEY`.

**Variables:**
- `PUBLIC_BASE_URL` = `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/midia` (as imagens ficam no branch `midia`, ver abaixo)
- `HORARIOS_PUBLICACAO` = `11:45,18:45` (padrão; `imediato` publica assim que você aprova)
- `IG_GRAPH_BASE` = `https://graph.facebook.com/v23.0` (login pelo Facebook) ou `https://graph.instagram.com/v23.0` (login pelo Instagram)
- `IG_HANDLE` = `@seuperfil`
- `MAX_POSTS` = `2` (posts por dia), `JANELA_DIAS` = `3`, `AVISAR_SEM_VOTACAO` = `0`
- `SITE_TESTE_URL` = endereço do teste, só quando o site estiver no ar
- `DRY_RUN` = `1` nas primeiras semanas. Assim o bot faz tudo, menos postar. Depois mude para `0`.

### 5. Rodar
- **Actions → Gerar posts do dia → Run workflow** para testar na hora. Depois disso, ele roda sozinho todo dia às 8h47 (Brasília).
- Os carrosséis chegam no Telegram com três botões:
  - **✅ Aprovar** coloca o post no próximo horário livre da fila.
  - **⚡ Agora** publica na próxima verificação, em até ~15 minutos.
  - **🗑️ Descartar** joga fora.
- Comandos no chat: `/fila` mostra o que está agendado, `/agora <id>` publica um agendado na hora, e `/aprovar <id>` e `/descartar <id>` funcionam como os botões.
- **Editar a legenda antes de publicar:** `/legenda <id>` devolve a legenda atual. Copie, edite e mande `/legenda <id>` com o texto novo na linha de baixo. A troca vale para o Instagram e o TikTok (limite de 2.200 caracteres e 30 hashtags).
- **Antes de tudo, rode *Actions → Diagnóstico → Run workflow*.** Ele confere cada integração e manda o resultado no Telegram.

## Rotina diária
- Cada execução olha os **últimos 3 dias** (`JANELA_DIAS`). Assim, se a API publicar uma votação com atraso, ela entra no dia seguinte.
- Uma votação nunca vira post duas vezes, e a **mesma proposição** não é repetida por 7 dias (`INTERVALO_PROPOSICAO_DIAS`). Isso evita postar o texto-base num dia e um destaque do mesmo projeto no outro.
- Em dias sem votação, como fins de semana e recesso, o bot fica em silêncio. Use `AVISAR_SEM_VOTACAO=1` se quiser receber o aviso.

## Voto da Semana
Todo **sábado às 10h47** (Brasília), o bot gera um post de imagem única (1080×1350) com um parlamentar em destaque e o voto dele nas principais pautas da semana (até 4).

- **Pautas:** as votações que viraram carrossel nos últimos 7 dias, menos as que você descartou. Se houver menos de 2, o bot coleta a semana direto da API.
- **Quem aparece:** rodízio automático e imparcial. O bot sorteia, com semente fixa por semana, alguém que participou das votações e ainda não apareceu. Ninguém repete antes de todos os elegíveis passarem.
- **Escolha manual:** em *Actions → Voto da Semana → Run workflow*, preencha o nome do parlamentar. Pela linha de comando: `python main.py semana --parlamentar "Nome" --forcar`.
- **Sem registro de voto** aparece como **NÃO VOTOU**, e a legenda explica que pode ser falta, licença ou missão oficial.
- **Senado:** `CASAS_SEMANA=camara,senado` gera um post por casa.
- **Teste visual:** `python main.py demo --modelo semana`.

A aprovação é igual à dos carrosséis: chega no Telegram com ✅/🗑️.

## Pautas frias (dias sem votação)
Se ficar **3 dias sem post** (`DIAS_SEM_POST_PARA_FRIA`) e não houver votação relevante, o comando diário gera **uma** pauta fria e manda para aprovação, marcada como 🧊 PAUTA FRIA. Como ela também conta como post, em recesso sai uma a cada 3 dias. Rascunhos descartados não contam.

O bot alterna entre duas fontes:
- **Explicadores** (`pautas_frias/*.yaml`): fila editorial, usada em ordem e uma vez só. Já vem com 10 posts, cada um citando o artigo da Constituição de onde vem a informação. O guia para escrever novos está em `pautas_frias/_COMO-ESCREVER.md`. Quando restarem 3, o bot avisa no Telegram.
- **Bancada do Estado**: gerada automaticamente pela API da Câmara, com os deputados em exercício de cada UF e os partidos. Faz rodízio pelas 27 UFs e depois recomeça, com os dados atualizados.

Comandos úteis:
- `python main.py fria`: gera a próxima pauta fria agora.
- `python main.py fria --arquivo 05-veto`: gera um explicador específico.
- `python main.py fria --uf MT`: gera a Bancada de Mato Grosso.
- `python main.py demo --modelo fria`: teste visual (use `--bancada` para a Bancada fictícia).

## Posts fixados (conversão)
São três carrosséis para o topo do perfil, pensados para quem chega pela primeira vez: **01 Quem somos**, **02 O que tem aqui** e **03 Faça parte**. Eles são publicados à mão, uma vez. Rode `python main.py fixados` para gerar as imagens em `fixados/` com o seu `IG_HANDLE`. As legendas e a ordem certa de fixação estão em `fixados/LEGENDAS.md`.

## Site: teste "Quem vota como você?"
A pessoa responde SIM, NÃO ou pula em votações reais. Cada pergunta tem um resumo neutro, o que significava votar SIM e o link para o texto oficial. No fim, o site mostra os **deputados** e os **senadores** que votaram mais parecido com ela, filtra por estado, mostra a afinidade por partido, compara voto a voto e gera um card para os Stories.

- **Curadoria:** `quiz/perguntas.yaml`. Você escolhe as votações e escreve os resumos, com pelo menos 8 da Câmara e 8 do Senado e no máximo 3 por tema.
- **Dados:** `python main.py quiz` gera `site/quiz.json` com os votos oficiais. `python main.py quiz --demo` gera dados fictícios para teste.
- **Cálculo no navegador:** as respostas não saem do aparelho. Deputados são comparados só com perguntas da Câmara, e senadores só com as do Senado. Abstenção e ausência saem da conta, e só aparece quem votou em pelo menos 60% das perguntas respondidas.
- **Publicação:** o workflow *Site do teste* publica a pasta `site/` no GitHub Pages a cada mudança e toda segunda-feira. Ative em *Settings → Pages → Source: GitHub Actions*.
- **Contador anônimo (opcional):** `contador/worker.js` é um Cloudflare Worker gratuito que guarda **só totais**, sem IP, cookie ou ID. Coloque a URL dele em `CONFIG.contadorUrl` no `site/index.html`. Sem isso, nada é enviado. Para publicar números ("72% dos participantes votariam SIM..."), lembre de dizer que a amostra não é científica e de pausar em períodos de campanha.
- **Antes de lançar:** vale uma revisão do texto de privacidade e dos avisos por um especialista em LGPD e direito eleitoral.

## Manutenção automática

### Precisão dos dados
- **Quórum:** em PEC (308 deputados e 49 senadores) e PLP (257 e 41), o placar mostra quantos votos SIM eram necessários e se o número foi alcançado ("faltaram 8"). Assim, uma PEC com 300 SIM × 10 NÃO não parece um erro quando sai "rejeitada". O formato de placar apertado passa a medir a distância até esse mínimo ("Teve 300. Precisava de 308."). Votações procedimentais dentro da PEC, como destaques e requerimentos, ficam de fora dessa regra.
- **Checagem automática:** antes de o rascunho chegar, o bot confere se o resultado bate com o placar e com o quórum, se a contagem voto a voto bate com o total oficial do Senado, se há parlamentar repetido, votos demais ou partido faltando, e se falta ementa ou link da fonte. Qualquer problema aparece no topo da mensagem como **⚠️ Confira antes de aprovar**.

### Fila de publicação
Aprovar não publica na hora: o post vai para o próximo horário livre de `HORARIOS_PUBLICACAO` (padrão 11h45 e 18h45, horário de Brasília), um post por horário. O verificador publica quando o horário chega (com até ~15 minutos de atraso do GitHub) e, se vários vencerem juntos, solta um por rodada. Instagram e TikTok saem juntos. Para notícia urgente, use **⚡ Agora**.

### Token do Instagram
Todo dia o bot confere se o token funciona e, no login pelo Instagram, renova uma vez por semana (o token vale 60 dias). O token novo é salvo sozinho no secret `IG_ACCESS_TOKEN`, usando o `GH_PAT`. Se algo falhar, chega um alerta no Telegram antes de um post quebrar.

**`GH_PAT`:** crie em *GitHub → Settings → Developer settings → Fine-grained tokens*, só para este repositório, com permissão **Secrets: Read and write**. Cadastre como secret `GH_PAT`. Ele serve para o Instagram e o TikTok.

### Diagnóstico
`python main.py diagnostico` (ou o workflow *Diagnóstico*) testa Telegram, Instagram (inclusive a cota de posts das últimas 24 h), as APIs da Câmara e do Senado, a IA, o site do teste e o TikTok. Cada item sai como ✅, ⚠️ ou ❌, com o motivo. Ele avisa, por exemplo, se o site foi ao ar com os dados fictícios ou se o `DRY_RUN` ficou ligado.

### Relatório semanal
Toda segunda de manhã chega no Telegram o resumo da semana: o que foi publicado, por tipo, os 3 posts com melhor pontuação, o ranking dos formatos, a variação de seguidores e o que precisa da sua atenção (rascunhos esperando, fila de explicadores acabando, token perto de vencer). Para pedir na hora: `python main.py relatorio`.

### Imagens fora do histórico
Cada post gera cerca de 1,6 MB de imagens. No histórico do Git, isso viraria mais de 1 GB por ano. Por isso as imagens não vão para o branch principal: ficam no branch **`midia`**, recriado a cada execução com **um único commit, sem histórico**, guardando só os posts pendentes e os dos últimos 21 dias (`scripts/midia.sh`). O branch principal guarda só textos, métricas e estado.

## Formatos validados, TikTok e repost

### Biblioteca de formatos (`formatos/`)
Cada arquivo descreve **uma estrutura** que funcionou: o tipo de gancho, o estilo da capa, a ordem dos slides, onde entra o teste e a primeira linha da legenda. O conteúdo é sempre do perfil.

- Vem com 8 formatos: 5 de votação (título na capa, pergunta na capa, placar na capa, placar apertado e **mapa por estado**) e 3 de pautas frias.
- O **mapa por estado** é um mapa em grade, um quadrado por unidade da federação, colorido pela proporção de votos SIM da bancada, com o placar de cada estado. A capa pergunta "Como votou cada estado?", e é o formato mais compartilhável.
- O bot testa os formatos em rodízio. Quando cada um tem **3 posts medidos**, passa a sortear com peso pela pontuação, então o que performa melhor aparece mais e os outros continuam sendo testados.
- `python main.py formatos` mostra quantas vezes cada formato foi usado e a pontuação média.
- Formatos com gancho de tom opinativo ou sensacionalista são recusados automaticamente.
- Para registrar formatos novos a partir dos posts virais que você analisa no Codex, o esquema e um prompt pronto estão em `formatos/_COMO-REGISTRAR.md`.
- Para testar um formato: `python main.py demo --formato votacao-pergunta`.

### Slide do teste (o "produto" no meio da sequência)
Quando `SITE_TESTE_URL` estiver definida, o slide "Quem vota como você? Faça o teste" entra nos carrosséis na posição que o formato pedir, e a legenda ganha uma linha de chamada. Sem a variável, nada muda.

### TikTok
Cada post ganha uma versão 1080×1920 em `tiktok/`, com o slide centralizado na área que a interface do TikTok não cobre, e uma legenda adaptada. A mesma aprovação no Telegram vale para Instagram e TikTok. O que acontece depois depende de `TIKTOK_MODO`:

| Modo | O que acontece | Requisitos |
|---|---|---|
| `manual` (padrão) | O bot manda as imagens **como arquivo** e a legenda pronta no Telegram, e você posta. | Nenhum |
| `rascunho` | O bot envia o carrossel para a **caixa de entrada do TikTok**. Chega uma notificação no app, e você escolhe a música e publica. | App no TikTok com o escopo `video.upload` aprovado |
| `direto` | Publica sozinho. **Sem auditoria do TikTok, a API só posta em conta privada e os posts ficam privados.** | App auditado pelo TikTok |

Se o modo automático falhar (falta de configuração, erro da API ou imagens que não chegaram ao site em 2 horas), o bot avisa e manda o pacote manual, para nenhum post se perder.

**Sobre a auditoria:** as diretrizes do TikTok listam como uso não aceito "uma ferramenta para subir conteúdo nas contas que você ou sua equipe gerenciam". Um app próprio como este dificilmente é aprovado para postagem pública direta. Por isso o modo recomendado é `rascunho`. Para postagem pública 100% automática, o caminho é um intermediário já auditado (ex.: Upload-Post, pago).

**Configurar os modos `rascunho` ou `direto`:**
1. **Domínio próprio no site.** O TikTok só baixa imagens de domínio verificado, e `github.io` não serve para isso. Aponte um domínio para o GitHub Pages (*Settings → Pages → Custom domain*).
2. **App no TikTok.** Em [developers.tiktok.com](https://developers.tiktok.com), crie um app com os produtos **Login Kit** e **Content Posting API**. Cadastre como Redirect URI `https://SEU_DOMINIO/tiktok-callback/`. Em *URL properties*, verifique o domínio (registro DNS) e ligue-o ao app. Peça o escopo `video.upload` (e `video.publish` para o modo direto).
3. **Login (uma vez).** Com `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` e `TIKTOK_REDIRECT_URI` no `.env`, rode `python main.py tiktok-login`, abra o link, autorize e rode o comando que a página de retorno mostrar. Ele imprime o **refresh token**.
4. **No GitHub:**
   - Secrets: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` e `TIKTOK_REFRESH_TOKEN`.
   - Variables: `TIKTOK_MODO=rascunho` e `TIKTOK_MIDIA_URL=https://SEU_DOMINIO/midia`.
   - **`GH_PAT`:** um token pessoal do GitHub com permissão de escrita em *Secrets* deste repositório. O TikTok pode trocar o refresh token a cada renovação, e o bot usa esse token para salvar o novo sozinho. Sem ele, o login expira.

Como as imagens chegam ao TikTok: os workflows que geram posts disparam o deploy do site, que publica as imagens 9:16 dos últimos 14 dias em `https://SEU_DOMINIO/midia/<post>/`. Se você aprovar antes de o deploy terminar, o bot tenta de novo a cada 15 minutos.

Limites do TikTok: 6 chamadas por minuto por conta e cerca de 15 posts por dia por conta, somando todos os apps.

### Métricas e repost
- O workflow *Métricas do Instagram* roda todo dia e grava alcance, salvamentos, compartilhamentos, curtidas e comentários dos posts com 2 a 30 dias.
- **Pontuação** = (3 × salvamentos + 3 × compartilhamentos + comentários + 0,5 × curtidas) ÷ alcance × 1000. Ela mede utilidade, não tamanho do perfil.
- **Repost:** as pautas frias passam a girar entre explicador, Bancada do Estado e repost. Um explicador volta quando está entre os **30% melhores** (com pelo menos 4 explicadores medidos) e saiu há mais de `REPOST_APOS_DIAS` (padrão 60). Ele é regerado com o texto atual do YAML e com o formato da vez, e chega no Telegram marcado como 🔁 REPOST, com os números da última vez.
- `python main.py repost` gera o repost do melhor candidato na hora.

## Identidade visual
O carrossel segue o **Guia de Marca "Como Vota, Deputado?" v1.0**:
- **Formato 1080×1080.** Capa e placar em Azul-Documentos; partidos e dissidentes em Off-White; slide final com o logo.
- **Cores:** Verde-Aprova (SIM), Vermelho-Rejeita (NÃO), Cinza-Urna (abstenção/faltou) e Amarelo-Voto só em chamadas e no carimbo OFICIAL.
- **Tipografia:** Archivo Black em caixa alta nos títulos, Inter no corpo e IBM Plex Mono em números e proposições. As fontes ficam embutidas em `bot/render/fonts/` (licença OFL), então o resultado é igual em qualquer máquina.
- **Ícones de voto ✓ ✕ —** desenhados em SVG, nunca emoji, também na legenda.
- **Elementos recorrentes:** carimbo OFICIAL no placar, linha de cédula pontilhada na lista de nomes e barra de resultado SIM × NÃO no rodapé.
- **Avatar:** `assets/avatar.png`, a versão monocromática do símbolo, para a foto de perfil.

Para mudar o visual, edite `bot/render/templates/carrossel.html` (slides) e `logo.svg` (logo).

## Regras editoriais (embutidas no código)
- Só entram votações **nominais** de Plenário. Votações simbólicas e secretas ficam de fora, porque não há voto individual.
- O texto parte da **ementa oficial**. A IA só reescreve em linguagem simples, com a instrução explícita de não opinar.
- Toda legenda traz o link da fonte oficial.
- Nada é publicado sem a sua aprovação.

## Próximos passos sugeridos
- Ajustar os pesos em `bot/selector.py` depois de ver algumas semanas reais.
- Criar uma página com a lista completa de votos (semente do SaaS). Quando ela existir, os posts podem voltar a apontar para o link da bio.
- Gerar uma versão Stories (1080x1920) a partir do mesmo template.
