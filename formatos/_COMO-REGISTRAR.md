# Biblioteca de formatos validados

Cada arquivo `.yaml` desta pasta é **uma estrutura** que funcionou: o tipo de gancho, a ordem dos slides, onde entra o teste e a primeira linha da legenda. **O conteúdo é sempre do próprio perfil.** Nada de texto, imagem ou dado de outra conta entra aqui.

O bot testa os formatos em rodízio. Quando cada um tiver pelo menos 3 posts medidos, ele passa a usar mais os que performam melhor (`python main.py formatos` mostra o placar).

## Campos

```yaml
id: votacao-pergunta            # único, igual ao nome do arquivo
aplica_a: votacao               # votacao | fria (explicadores e Bancada do Estado)
nome: Pergunta na capa
gancho: pergunta direta ao leitor   # descrição livre, para você
ativo: true                     # false tira do rodízio sem apagar
origem: De onde veio a estrutura (ex.: "padrão visto em posts de dados, out/2026")

# primeira linha da legenda (é a que aparece no feed)
legenda_gancho: "Como votaram os {quem_plural}? {titulo}"

# --- só para aplica_a: votacao ---
capa: pergunta                  # classico | pergunta | numero | apertado | estados
faixa_capa: Arraste e veja →
sequencia: [capa, placar, cta_teste, partidos, dissidentes, final]
quando:                         # opcional: só usa o formato se...
  margem_max: 0.10              # ...a diferença SIM×NÃO for de até 10% dos votos
  # margem_min: 0.5             # ...ou de pelo menos 50% (votação folgada)
  # casa: senado                # ...ou só para uma Casa

# --- só para aplica_a: fria ---
capa_kicker: Você sabia?        # texto pequeno acima do título (opcional)
faixa_capa: Arraste para entender →
cta_teste: meio                 # meio | antes_final | nao
```

**Slides disponíveis para votação:** `capa`, `placar`, `partidos`, `dissidentes`, `mapa`, `cta_teste` e `final`. A sequência sempre começa em `capa` e termina em `final`. `dissidentes` some sozinho quando ninguém votou contra o partido ou quando a votação é do Senado. `cta_teste` só aparece quando o site do teste estiver no ar (`SITE_TESTE_URL`).

**Variáveis da legenda:**
- Votação: `{titulo}`, `{titulo_min}`, `{proposicao}`, `{casa}`, `{na_casa}`, `{quem_plural}`, `{sim}`, `{nao}`, `{diferenca}`, `{diferenca_txt}`, `{resultado}`, `{quorum}` (votos SIM necessários em PEC/PLP; vazio nas demais) e `{decisao_txt}` ("Decidido por 4 votos na Câmara" ou, com quórum, "300 votos SIM na Câmara, eram necessários 308").
- Pautas frias: `{titulo}`, `{titulo_min}` e `{serie}`.

**Neutralidade:** o bot recusa formatos cujo gancho, kicker ou faixa usem palavras de tom opinativo ou sensacionalista ("polêmico", "vergonha", "absurdo", "escândalo"...). A lista está em `bot/formatos.py`.

## Prompt para o Codex

Cole isto no Codex junto com os posts que você separou (prints ou links):

> Analise estes posts que performaram bem nos últimos 7 dias. Para cada um, descreva **apenas a estrutura**: o tipo de gancho do primeiro slide, a ordem e a função de cada slide, onde aparece a chamada para ação e como é a primeira linha da legenda.
>
> Depois, proponha até 3 formatos para o perfil "Como Vota Deputado?", que publica como os parlamentares votaram no Congresso, sem opinião e com dados oficiais. Responda em YAML, um bloco por formato, seguindo exatamente este esquema: [cole aqui a seção "Campos" acima].
>
> Regras: não reaproveite nenhum texto, frase ou imagem dos posts analisados. O gancho tem que ser factual e neutro, sem adjetivos de valor, sem ironia e sem apelo emocional. Use apenas os tipos de slide e as variáveis listados no esquema.

Revise o que o Codex devolver, salve cada formato como `formatos/<id>.yaml` e rode `python main.py formatos` para conferir se foram aceitos.
