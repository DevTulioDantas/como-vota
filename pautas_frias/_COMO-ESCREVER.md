# Como escrever uma pauta fria

Cada arquivo `.yaml` desta pasta vira um carrossel. O bot usa os arquivos **em ordem de nome**, e cada um só uma vez. Para controlar a ordem, numere os arquivos (`11-...yaml`, `12-...yaml`). Arquivos que começam com `_`, como este, são ignorados.

## Estrutura

```yaml
titulo: O que é uma PEC?                    # capa (até ~50 caracteres fica melhor)
resumo: Uma ou duas frases para a capa e a legenda.
fonte: Constituição Federal, art. 60        # aparece no rodapé de todo slide e na legenda
slides:                                     # de 1 a 8 slides (capa e final são automáticos)
  - tipo: texto
    titulo: Título do slide
    texto: Parágrafo curto (até ~230 caracteres fica grande e legível).
    itens:                                  # opcional: lista com marcadores
      - Item um
      - Item dois
    rodape: Observação menor no fim (opcional).

  - tipo: numero                            # número gigante em destaque
    numero: "308"                           # use aspas
    rotulo: votos na Câmara
    texto: Explicação do número.

  - tipo: passos                            # sequência numerada (até 6 passos)
    titulo: Passo a passo
    passos:
      - "Primeiro passo"
      - "Segundo passo"

  - tipo: votos                             # legenda de votos com os ícones da marca
    titulo: O que cada voto significa
    itens:
      - voto: Sim                           # Sim | Não | Abstenção | Obstrução | Ausente
        rotulo: SIM
        texto: Explicação.
```

Se o texto tiver dois-pontos (`:`), coloque-o entre aspas.

## Regras editoriais
- **Linguagem simples:** escreva para quem nunca acompanhou o Congresso. Frases curtas, palavras do dia a dia e números concretos ("3 em cada 5 deputados", não "3/5"; "mais da metade", não "maioria absoluta"). Se precisar de um termo técnico (veto, relator, plenário), explique na mesma frase.
- **Só fatos verificáveis**, sempre com a fonte. Prefira a Constituição, os regimentos e as leis, que mudam pouco.
- **Nada que envelheça rápido:** evite nomes de quem ocupa cargos, números de votações recentes e "este ano".
- **Sem opinião** sobre o mérito de leis, partidos ou políticos.
- Para testar o visual antes de entrar na fila: `python main.py fria --arquivo 11-meu-arquivo --sem-telegram`. As imagens ficam em `data/drafts/`. Esse comando gera o rascunho na hora e marca o arquivo como usado.

## Ideias para próximos posts
O que faz uma CPI · Quórum: o que é e por que derruba sessões · O que são as comissões permanentes · Regime de urgência · O que é um destaque · Sessão conjunta do Congresso · O que faz o presidente da Câmara · Recesso parlamentar: quando e por quê · Federação partidária · Imunidade parlamentar · Como funciona a LDO e a LOA (orçamento)
