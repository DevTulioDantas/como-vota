"""Como Vota — bot publicador.

Comandos:
  python main.py gerar        coleta a semana, escolhe votações, gera carrosséis e manda para aprovação
  python main.py verificar    lê as aprovações do Telegram e publica no Instagram
  python main.py semana       gera o "Voto da Semana" (parlamentar em destaque) e manda para aprovação
  python main.py fria         gera a próxima pauta fria agora (explicador ou Bancada do Estado)
  python main.py fixados      gera os 3 posts fixados de conversão em fixados/ (publicação manual)
  python main.py quiz         exporta os dados do teste "Quem vota como você?" para site/quiz.json
  python main.py formatos     lista a biblioteca de formatos e o desempenho de cada um
  python main.py metricas     atualiza as métricas do Instagram dos posts publicados
  python main.py repost       gera agora o repost do explicador com melhor desempenho
  python main.py token-instagram  confere o token do Instagram e renova quando for a hora
  python main.py diagnostico  confere toda a configuração (Telegram, Instagram, APIs, site, TikTok)
  python main.py relatorio    manda o resumo da semana no Telegram
  python main.py tiktok-login faz o login do TikTok (uma vez) e mostra o token para guardar como secret
  python main.py midia-site   copia as imagens 9:16 recentes para site/midia (hospedagem para o TikTok)
  python main.py publicar ID  publica um rascunho direto (sem Telegram)
  python main.py demo         gera um post FICTÍCIO para testar o visual (sem internet)
                              --modelo carrossel (padrão) | semana | fria   --formato <id>
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

from bot import agenda, approval, cta, formatos, frias, metricas, publisher, selector, semana, storage, tiktok, tiktok_api, token_ig
from bot.collectors import camara, senado
from bot.models import Votacao
from bot.render.renderer import renderizar, renderizar_explicador, renderizar_fixados, renderizar_voto_semana
from bot.summarizer import gerar_textos

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("como-vota")

HANDLE = os.getenv("IG_HANDLE") or "@comovotadeputado"
COLETORES = {"camara": camara.coletar, "senado": senado.coletar}


def _telegram_ativo() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def _exportar_tiktok(rid: str, legenda: str) -> None:
    if not tiktok.ativo():
        return
    try:
        tiktok.exportar(storage.pasta(rid), legenda)
    except Exception:
        log.exception("Falha ao gerar a versão TikTok de %s (o post do Instagram segue normal)", rid)


TIKTOK_TENTATIVAS = 8  # ~2 horas, com o verificador rodando a cada 15 minutos


def _tiktok_pendentes() -> list[str]:
    """Rascunhos aprovados cujo envio ao TikTok está esperando o site atualizar."""
    pend = []
    for meta in metricas.todas_as_metas():
        if (meta.get("tiktok") or {}).get("status") == "AGUARDANDO_SITE":
            pend.append(meta["id"])
    return pend


def _enviar_tiktok(rid: str) -> None:
    """Depois da aprovação: publica no TikTok pela API (modo rascunho/direto) ou,
    no modo manual e em caso de falha, manda o pacote 9:16 pelo Telegram. Uma vez só."""
    pasta = storage.pasta(rid) / "tiktok"
    imgs = sorted(pasta.glob("slide_*.jpg"))
    if not imgs:
        return
    meta = storage.carregar_meta(rid)
    if meta.get("tiktok_enviado") or (meta.get("tiktok") or {}).get("status") in tiktok_api.STATUS_OK:
        return
    arq = pasta / "legenda.txt"
    legenda = arq.read_text(encoding="utf-8") if arq.exists() else ""

    falta = tiktok_api.faltando() if tiktok_api.modo() != "manual" else []
    if falta:
        log.warning("TIKTOK_MODO=%s, mas faltam as variáveis %s: usando o modo manual", tiktok_api.modo(), ", ".join(falta))
        if _telegram_ativo():
            approval.avisar(f"⚠️ TikTok automático desligado: faltam as variáveis {', '.join(falta)}. "
                            "Mando o pacote para você postar à mão.")
    elif tiktok_api.modo() != "manual":
        try:
            res = tiktok_api.publicar(tiktok_api.urls_midia(rid, imgs), legenda)
            meta["tiktok"] = {**res, "em": storage.agora()}
            storage.salvar_meta(rid, meta)
            if _telegram_ativo():
                if res["status"] == "DRY_RUN":
                    approval.avisar(f"🎵 TikTok [DRY_RUN]: {rid} seria enviado ({res['modo']}).")
                elif res["status"] == "SEND_TO_USER_INBOX":
                    approval.avisar(f"🎵 TikTok: {rid} está na caixa de entrada do app. "
                                    "Abra a notificação, escolha a música e publique.")
                elif res["status"] == "PUBLISH_COMPLETE":
                    approval.avisar(f"🎵 TikTok: {rid} publicado.")
                else:
                    approval.avisar(f"🎵 TikTok: {rid} enviado ({res['status']}). Confira o app em alguns minutos.")
            return
        except tiktok_api.ImagemForaDoAr as e:
            anterior = meta.get("tiktok") or {}
            tentativas = anterior.get("tentativas", 0) + 1 if anterior.get("status") == "AGUARDANDO_SITE" else 1
            if tentativas <= TIKTOK_TENTATIVAS:
                meta["tiktok"] = {"modo": tiktok_api.modo(), "status": "AGUARDANDO_SITE",
                                  "tentativas": tentativas, "erro": str(e), "em": storage.agora()}
                storage.salvar_meta(rid, meta)
                log.info("%s: imagens ainda não estão no site; nova tentativa na próxima verificação", rid)
                return
            log.warning("%s: imagens não apareceram no site depois de %d tentativas", rid, tentativas - 1)
            if _telegram_ativo():
                approval.avisar(f"⚠️ TikTok: as imagens de {rid} não chegaram ao site. Mando o pacote para postar à mão.")
        except Exception as e:
            log.exception("TikTok automático falhou para %s", rid)
            meta["tiktok"] = {"modo": tiktok_api.modo(), "status": "ERRO", "erro": str(e), "em": storage.agora()}
            storage.salvar_meta(rid, meta)
            if _telegram_ativo():
                approval.avisar(f"⚠️ TikTok automático falhou ({e}). Mando o pacote para você postar à mão.")

    if not _telegram_ativo():
        return
    try:
        approval.enviar_pacote_tiktok(rid, imgs, legenda)
        meta["tiktok_enviado"] = storage.agora()
        storage.salvar_meta(rid, meta)
    except Exception as e:
        log.warning("Não consegui enviar o pacote TikTok de %s: %s", rid, e)


def criar_rascunho(v: Votacao, estado: dict, demo: bool = False, enviar: bool = True,
                   formato_id: str | None = None, aviso_extra: str = "", registrar_formato: bool = True) -> str:
    textos = gerar_textos(v, HANDLE)
    fmt = formatos.escolher("votacao", estado, info=formatos.info_votacao(v), semente=v.id, forcar=formato_id)
    textos["legenda"] = cta.adicionar_na_legenda(
        formatos.aplicar_gancho(textos["legenda"], None if textos.get("gancho") else fmt,
                                formatos.variaveis_votacao(v, textos)))
    imgs = renderizar(v, textos, storage.pasta(v.id), HANDLE, demo=demo, formato=fmt)
    _exportar_tiktok(v.id, textos["legenda"])
    from bot import qualidade
    alertas = qualidade.checar(v) + qualidade.checar_textos(textos)
    storage.salvar_meta(v.id, {
        "id": v.id, "status": "gerado", "criado_em": storage.agora(), "formato": fmt["id"] if fmt else None,
        "alertas": alertas,
        "textos": textos, "votacao": v.to_dict(), "historico": [], "demo": demo,
    })
    estado["rascunhos"][v.id] = "gerado"
    if not demo and registrar_formato:
        formatos.registrar_uso(estado, fmt)
    log.info("Rascunho %s (%s): %d imagens em %s", v.id, fmt["id"] if fmt else "sem formato", len(imgs), storage.pasta(v.id))

    for a in alertas:
        log.warning("%s: %s", v.id, a)
    if enviar and _telegram_ativo():
        aviso = aviso_extra + (("⚠️ Confira antes de aprovar:\n" + "\n".join(f"• {a}" for a in alertas) + "\n\n")
                               if alertas else "")
        approval.enviar_para_aprovacao(v.id, imgs, aviso + textos["legenda"])
        storage.atualizar_status(estado, v.id, "enviado")
    return v.id


def _rascunhos_abertos() -> list[dict]:
    """Rascunhos de votação ainda não aprovados (gerados ou à espera no Telegram)."""
    saida = []
    for rid, status in storage.carregar_estado().get("rascunhos", {}).items():
        if status in ("gerado", "enviado") and rid.startswith(("camara-", "senado-")):
            try:
                saida.append(storage.carregar_meta(rid))
            except FileNotFoundError:
                continue
    return saida


def _explicacao_nova(meta: dict) -> bool:
    from bot.summarizer import explicacao_escrita
    nova = explicacao_escrita(Votacao.from_dict(meta["votacao"]))
    atual = meta.get("textos", {})
    # o título fica de fora: quando há apelido, o post usa o apelido, não o título do arquivo
    return bool(nova) and any(nova.get(k) != atual.get(k) for k in ("resumo", "detalhes", "chamada", "gancho", "hashtags", "publico"))


def cmd_pendentes(args) -> None:
    """O que o agente precisa explicar: rascunhos abertos sem texto no explicacoes.yaml e sem texto da IA."""
    from bot.summarizer import explicacoes
    feitas = explicacoes()
    # texto escrito pela IA na geração não precisa do agente: ele só cobre as falhas (cota, bloqueio...)
    pendentes = [m for m in _rascunhos_abertos() if m["votacao"]["proposicao"] not in feitas
                 and m.get("textos", {}).get("fonte_texto") != "ia"]
    if not pendentes:
        print("Nenhuma votação pendente de explicação.")
    for m in pendentes:
        v = m["votacao"]
        print(f"## {v['proposicao']}  ({m['id']}, {v['casa']}, {v['data']})")
        print(f"Ementa oficial: {v['ementa']}")
        print(f"O que foi votado: {v['descricao']}")
        print(f"Fonte: {v['url_fonte']}\n")


def cmd_refazer(args) -> None:
    """Gera de novo rascunhos ainda não aprovados, com o código e os dados atuais,
    no mesmo formato, e manda a versão nova para o Telegram.
    Com --explicados, refaz os que ganharam ou mudaram texto no explicacoes.yaml."""
    estado = storage.carregar_estado()
    ids = list(args.ids)
    if args.explicados:
        ids += [r["id"] for r in _rascunhos_abertos() if _explicacao_nova(r)]
        if not ids:
            log.info("Nenhum rascunho aberto com explicação nova no explicacoes.yaml")
    for rid in dict.fromkeys(ids):
        try:
            meta = storage.carregar_meta(rid)
        except FileNotFoundError:
            log.error("Rascunho %s não existe", rid)
            continue
        if meta.get("status") in ("publicado", "aprovado", "agendado"):
            log.warning("%s está %s: não refaço o que já foi aprovado", rid, meta["status"])
            continue
        antiga = Votacao.from_dict(meta["votacao"])
        try:  # dados frescos: pega correções da API e campos novos (apelido, totais oficiais)
            v = camara.coletar_por_id(rid) if antiga.casa == "camara" else senado.coletar_por_id(rid, antiga.data)
        except Exception as e:
            log.warning("Não consegui coletar %s de novo (%s); uso os dados salvos", rid, e)
            v = None
        criar_rascunho(v or antiga, estado, enviar=not args.sem_telegram, formato_id=meta.get("formato"),
                       registrar_formato=False,
                       aviso_extra="🔁 Versão refeita deste post. Ignore a mensagem anterior.\n\n")
    storage.salvar_estado(estado)


def cmd_consultar(args) -> None:
    """Pergunta livre ao Gemini (padrão: como deixar os posts mais interessantes); resposta no Telegram."""
    from bot import consulta
    resposta = consulta.consultar(args.pergunta or "")
    print(resposta)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as resumo:
            resumo.write(resposta)
    if _telegram_ativo():
        partes = [resposta[i:i + 3900] for i in range(0, len(resposta), 3900)] or ["(resposta vazia)"]
        for i, parte in enumerate(partes, 1):
            approval.avisar(f"🤖 Consulta à IA ({i}/{len(partes)})\n\n{parte}")


def cmd_gerar(args) -> None:
    fim = date.fromisoformat(args.fim) if args.fim else date.today()
    # Janela de alguns dias + deduplicação: pega votações que a API publicou
    # com atraso sem nunca repetir post (ver storage.ja_existe / proposicao_recente).
    inicio = date.fromisoformat(args.inicio) if args.inicio else fim - timedelta(days=args.janela)
    estado = storage.carregar_estado()

    todas: list[Votacao] = []
    for casa in args.casas.split(","):
        try:
            todas += COLETORES[casa](inicio.isoformat(), fim.isoformat())
        except Exception as e:
            log.error("Falha ao coletar %s: %s", casa, e)
            if _telegram_ativo():
                approval.avisar(f"⚠️ Falha ao coletar votações de {casa}: {e}")

    novas = [
        v for v in todas
        if not storage.ja_existe(v.id)
        and not storage.proposicao_recente(v.casa, v.proposicao, dias=args.intervalo_proposicao)
    ]
    escolhidas = selector.selecionar(novas, maximo=args.max)
    log.info("%d votações coletadas, %d novas, %d escolhidas", len(todas), len(novas), len(escolhidas))

    # Dia sem votação é normal (fins de semana, recesso): só avisa se pedirem.
    if not escolhidas and _telegram_ativo() and os.getenv("AVISAR_SEM_VOTACAO") == "1":
        approval.avisar(f"ℹ️ Nenhuma votação nominal relevante entre {inicio:%d/%m} e {fim:%d/%m}.")

    for v in escolhidas:
        try:
            criar_rascunho(v, estado, enviar=not args.sem_telegram)
        except Exception as e:
            log.exception("Erro ao gerar rascunho de %s", v.id)
            if _telegram_ativo():
                approval.avisar(f"⚠️ Erro ao gerar {v.id}: {e}")

    # Pauta fria: só quando não há votação para postar E o perfil está parado há alguns dias.
    if not escolhidas and frias.precisa_de_fria(args.dias_sem_post):
        log.info("Nenhum post nos últimos %d dias: gerando pauta fria", args.dias_sem_post)
        try:
            gerar_fria(estado, enviar=not args.sem_telegram)
        except Exception as e:
            log.exception("Erro ao gerar pauta fria")
            if _telegram_ativo():
                approval.avisar(f"⚠️ Erro ao gerar pauta fria: {e}")
    storage.salvar_estado(estado)


def gerar_fria(estado: dict, item: dict | None = None, demo: bool = False, enviar: bool = True,
               formato_id: str | None = None) -> str | None:
    avisos: list[str] = []
    if item is None:
        item, avisos = frias.escolher(estado)
    for a in avisos:
        log.info(a)
        if enviar and _telegram_ativo() and not demo:
            approval.avisar(a)
    if item is None:
        log.warning("Nenhuma pauta fria disponível")
        return None

    rid = item["id"] + ("-demo" if demo else "")
    fmt = formatos.escolher("fria", estado, semente=rid, forcar=formato_id)
    imgs = renderizar_explicador(item, storage.pasta(rid), HANDLE, demo=demo, formato=fmt)
    legenda = cta.adicionar_na_legenda(
        formatos.aplicar_gancho(frias.legenda(item), fmt, formatos.variaveis_fria(item)))
    _exportar_tiktok(rid, legenda)
    storage.salvar_meta(rid, {
        "id": rid, "tipo": "fria", "fonte_tipo": item["fonte_tipo"], "status": "gerado",
        "formato": fmt["id"] if fmt else None, "base_id": item.get("base_id") or item["id"],
        "criado_em": storage.agora(), "textos": {"titulo": item["titulo"], "legenda": legenda},
        "item": item, "historico": [], "demo": demo,
    })
    estado["rascunhos"][rid] = "gerado"
    if not demo:
        frias.registrar_uso(estado, item)
        formatos.registrar_uso(estado, fmt)
    log.info("Pauta fria %s (%s): %d imagens", rid, fmt["id"] if fmt else "sem formato", len(imgs))

    if enviar and _telegram_ativo():
        rotulo = item.get("repost_info") or "🧊 PAUTA FRIA"
        approval.enviar_para_aprovacao(rid, imgs, f"{rotulo}\n\n{legenda}")
        storage.atualizar_status(estado, rid, "enviado")
    return rid


def cmd_fria(args) -> None:
    estado = storage.carregar_estado()
    item = None
    if args.arquivo:
        alvo = args.arquivo.removesuffix(".yaml").removesuffix(".yml")
        item = next((i for i in frias.carregar_fila() if i["id"] in (f"fria-{alvo}", alvo)), None)
        if item is None:
            sys.exit(f"Explicador não encontrado: {args.arquivo}")
    elif args.uf:
        item = frias.bancada(args.uf.upper())
    gerar_fria(estado, item=item, enviar=not args.sem_telegram)
    storage.salvar_estado(estado)


def _publicar(estado: dict, rid: str) -> None:
    base = os.environ["PUBLIC_BASE_URL"].rstrip("/")
    meta = storage.carregar_meta(rid)
    urls = [f"{base}/{rid}/{img.name}" for img in storage.imagens(rid)]
    try:
        res = publisher.publicar(urls, meta["textos"]["legenda"])
        storage.atualizar_status(estado, rid, "publicado", instagram_id=res["id"], permalink=res["permalink"])
        if _telegram_ativo():
            approval.avisar(f"✅ Publicado: {rid}\n{res['permalink']}")
    except Exception as e:
        log.exception("Erro ao publicar %s", rid)
        storage.atualizar_status(estado, rid, "erro", erro=str(e))
        if _telegram_ativo():
            approval.avisar(f"❌ Erro ao publicar {rid}: {e}\nMande /agora {rid} para tentar de novo.")
    _enviar_tiktok(rid)


def _agendar(estado: dict, rid: str) -> None:
    metas = metricas.todas_as_metas()
    slot = agenda.proximo_horario(agenda.ocupados(metas))
    if slot is None:  # HORARIOS_PUBLICACAO=imediato
        storage.atualizar_status(estado, rid, "aprovado")
        _publicar(estado, rid)
        return
    storage.atualizar_status(estado, rid, "agendado", agendado_para=slot.isoformat())
    log.info("%s agendado para %s", rid, slot.isoformat())
    if _telegram_ativo():
        approval.avisar(f"⏰ {rid} agendado para {agenda.descrever(slot)}. Para publicar já, mande /agora {rid}")


LIMITE_LEGENDA_IG = 2200
LIMITE_HASHTAGS_IG = 30


def _legenda(rid: str, nova: str) -> None:
    """/legenda <id> mostra a legenda atual; com texto novo, troca no Instagram e no TikTok."""
    if not (storage.pasta(rid) / "meta.json").exists():
        approval.avisar(f"Não encontrei o rascunho {rid}.")
        return
    meta = storage.carregar_meta(rid)
    if not nova:
        approval.avisar(f"✏️ Legenda atual de {rid} (copie, edite e mande de volta como "
                        f"/legenda {rid} + o texto na linha de baixo):")
        approval.avisar(meta["textos"]["legenda"])
        return
    if meta.get("status") in ("publicado", "descartado"):
        approval.avisar(f"{rid} já foi {meta['status']}: a legenda não pode mais ser trocada por aqui.")
        return
    hashtags = sum(1 for p in nova.split() if p.startswith("#"))
    if len(nova) > LIMITE_LEGENDA_IG or hashtags > LIMITE_HASHTAGS_IG:
        approval.avisar(f"⚠️ Legenda não trocada: o Instagram aceita até {LIMITE_LEGENDA_IG} caracteres "
                        f"e {LIMITE_HASHTAGS_IG} hashtags (a nova tem {len(nova)} e {hashtags}).")
        return
    meta["textos"]["legenda"] = nova
    meta["legenda_editada_em"] = storage.agora()
    storage.salvar_meta(rid, meta)
    pasta_tk = storage.pasta(rid) / "tiktok"
    if pasta_tk.exists():
        (pasta_tk / "legenda.txt").write_text(tiktok.legenda_tiktok(nova), encoding="utf-8")
    approval.avisar(f"✏️ Legenda de {rid} atualizada ({len(nova)} caracteres). Vale para Instagram e TikTok.")


def _mostrar_fila() -> None:
    metas = [m for m in metricas.todas_as_metas() if m.get("status") == "agendado" and m.get("agendado_para")]
    metas.sort(key=lambda m: m["agendado_para"])
    if not metas:
        texto = "📭 Nada agendado."
    else:
        linhas = [f"• {agenda.descrever(datetime.fromisoformat(m['agendado_para']))}: {m['id']}" for m in metas]
        texto = "⏰ Fila de publicação:\n" + "\n".join(linhas)
    if _telegram_ativo():
        approval.avisar(texto)
    print(texto)


def cmd_verificar(args) -> None:
    estado = storage.carregar_estado()
    decisoes, estado["telegram_offset"] = approval.ler_decisoes(estado.get("telegram_offset", 0))
    storage.salvar_estado(estado)  # salva o offset logo, para não reprocessar cliques

    processados = set()
    for decisao in decisoes:
        acao, rid = decisao[0], decisao[1]
        if acao == "fila":
            _mostrar_fila()
            continue
        if acao == "legenda":
            _legenda(rid, decisao[2] if len(decisao) > 2 else "")
            continue
        processados.add(rid)
        status = estado["rascunhos"].get(rid)
        if status is None:
            approval.avisar(f"Não encontrei o rascunho {rid}.")
            continue
        if status in ("publicado", "descartado"):
            continue  # clique repetido
        if acao == "descartar":
            storage.atualizar_status(estado, rid, "descartado")
            log.info("%s descartado", rid)
        elif acao == "agora":
            storage.atualizar_status(estado, rid, "aprovado")
            _publicar(estado, rid)
        elif status != "agendado":  # aprovar de novo um agendado não muda o horário
            _agendar(estado, rid)
        storage.salvar_estado(estado)
    log.info("%d decisões processadas", len(decisoes))

    # Publica o agendado que venceu (um por rodada, para espaçar os posts).
    for rid in agenda.vencidos(metricas.todas_as_metas())[:1]:
        processados.add(rid)
        storage.atualizar_status(estado, rid, "aprovado")
        _publicar(estado, rid)
        storage.salvar_estado(estado)

    for rid in _tiktok_pendentes():
        if rid not in processados:  # o recém-aprovado já tentou nesta rodada
            _enviar_tiktok(rid)


def cmd_publicar(args) -> None:
    estado = storage.carregar_estado()
    _publicar(estado, args.id)
    storage.salvar_estado(estado)


def gerar_voto_semana(pautas, casa: str, fim: date, estado: dict, nome: str | None = None,
                      demo: bool = False, enviar: bool = True, forcar: bool = False) -> str | None:
    rid = semana.id_rascunho(casa, fim) + ("-demo" if demo else "")
    if storage.ja_existe(rid) and not forcar:
        log.info("%s já existe; use --forcar para gerar de novo", rid)
        return None

    pautas = semana.ordenar_e_limitar(pautas)
    if len(pautas) < 2:
        log.info("Voto da Semana: só %d pauta(s) em %s; nada gerado", len(pautas), casa)
        if _telegram_ativo() and enviar:
            approval.avisar(f"ℹ️ Voto da Semana ({casa}): menos de 2 votações nominais relevantes na semana.")
        return None

    historico = estado.setdefault("voto_da_semana", {}).setdefault(casa, [])
    parlamentar = semana.escolher(pautas, historico, semente=rid, nome=nome)
    if parlamentar is None:
        msg = f"Não encontrei um parlamentar único com o nome \"{nome}\"." if nome else "Nenhum parlamentar elegível."
        log.error(msg)
        if _telegram_ativo() and enviar:
            approval.avisar(f"⚠️ Voto da Semana: {msg}")
        return None

    dados = semana.montar(pautas, parlamentar, fim)
    img = renderizar_voto_semana(dados, storage.pasta(rid) / "slide_01.jpg", demo=demo)
    legenda = cta.adicionar_na_legenda(semana.legenda(dados))
    _exportar_tiktok(rid, legenda)
    storage.salvar_meta(rid, {
        "id": rid, "tipo": "semana", "status": "gerado", "criado_em": storage.agora(),
        "textos": {"legenda": legenda}, "dados": dados, "historico": [], "demo": demo,
    })
    estado["rascunhos"][rid] = "gerado"
    if dados["chave"] not in historico:
        historico.append(dados["chave"])
    log.info("Voto da Semana %s: %s (%s-%s)", rid, dados["nome"], dados["partido"], dados["uf"])

    if enviar and _telegram_ativo():
        approval.enviar_para_aprovacao(rid, [img], legenda)
        storage.atualizar_status(estado, rid, "enviado")
    return rid


def cmd_semana(args) -> None:
    fim = date.fromisoformat(args.fim) if args.fim else date.today()
    estado = storage.carregar_estado()
    for casa in args.casas.split(","):
        pautas = semana.pautas_dos_rascunhos(casa, fim)
        if len(pautas) < 2:  # poucos rascunhos: coleta a semana direto da API
            try:
                coletadas = COLETORES[casa]((fim - timedelta(days=7)).isoformat(), fim.isoformat())
                escolhidas = selector.selecionar(coletadas, maximo=semana.MAX_PAUTAS)
                pautas = [(v, gerar_textos(v, HANDLE)) for v in escolhidas]
            except Exception as e:
                log.error("Falha ao coletar %s: %s", casa, e)
        try:
            gerar_voto_semana(pautas, casa, fim, estado, nome=args.parlamentar,
                              enviar=not args.sem_telegram, forcar=args.forcar)
        except Exception as e:
            log.exception("Erro no Voto da Semana de %s", casa)
            if _telegram_ativo():
                approval.avisar(f"⚠️ Erro no Voto da Semana ({casa}): {e}")
        storage.salvar_estado(estado)


def cmd_fixados(args) -> None:
    from pathlib import Path
    pasta = Path(__file__).resolve().parent / "fixados"
    for nome, imgs in renderizar_fixados(pasta, HANDLE).items():
        log.info("%s: %d imagens em %s", nome, len(imgs), pasta / nome)
    log.info("Legendas e ordem de fixação: %s", pasta / "LEGENDAS.md")


def cmd_quiz(args) -> None:
    from bot import quiz
    if args.demo:
        dados = quiz.exportar_demo()
    else:
        curadoria = quiz.carregar_curadoria()
        if not curadoria:
            sys.exit("quiz/perguntas.yaml está vazio. Escolha as votações ou use --demo.")
        temas = quiz.resumo_temas(curadoria)
        excesso = [t for t, n in temas.items() if n > 3]
        if excesso:
            log.warning("Temas com mais de 3 perguntas (teste pode ficar desequilibrado): %s", ", ".join(excesso))
        dados = quiz.exportar(curadoria)
    quiz.salvar(dados)


def cmd_metricas(args) -> None:
    n = metricas.coletar()
    log.info("Métricas atualizadas de %d posts", n)


def cmd_relatorio(args) -> None:
    from bot import relatorio
    if args.se_segunda and datetime.now(agenda.FUSO).weekday() != 0:
        log.info("Relatório semanal só sai às segundas")
        return
    texto = relatorio.montar(storage.carregar_estado())
    print(texto)
    if _telegram_ativo():
        approval.avisar(texto)


def cmd_diagnostico(args) -> None:
    from bot import diagnostico
    itens = diagnostico.rodar()
    texto = diagnostico.texto(itens)
    print(texto)
    if args.telegram and _telegram_ativo():
        approval.avisar(texto)
    if any(i[0] == diagnostico.ERRO for i in itens):
        sys.exit(1)


def cmd_token_instagram(args) -> None:
    estado = storage.carregar_estado()
    ok, msg = token_ig.manter(estado)
    storage.salvar_estado(estado)
    (log.info if ok else log.error)("Instagram: %s", msg)
    if not ok and _telegram_ativo():
        approval.avisar(msg)
    if not ok:
        sys.exit(1)


def cmd_repost(args) -> None:
    estado = storage.carregar_estado()
    candidatos = frias.candidatos_repost(estado)
    if args.base:
        candidatos = [g for g in candidatos if g["base_id"] in (args.base, f"fria-{args.base}")]
    if not candidatos:
        sys.exit("Nenhum explicador pronto para repost. É preciso ter pelo menos "
                 f"{frias.REPOST_MIN_AMOSTRA} explicadores medidos, e o escolhido precisa estar entre os 30% "
                 f"melhores e ter saído há mais de {frias._dias_repost()} dias.")
    item = frias.item_repost(candidatos[0])
    gerar_fria(estado, item=item, enviar=not args.sem_telegram)
    storage.salvar_estado(estado)


def cmd_tiktok_login(args) -> None:
    import secrets
    redirect = os.getenv("TIKTOK_REDIRECT_URI")
    falta = [n for n in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET") if not os.getenv(n)] + ([] if redirect else ["TIKTOK_REDIRECT_URI"])
    if falta:
        sys.exit("Defina no .env: " + ", ".join(falta))
    if not args.codigo:
        escopos = "user.info.basic,video.upload" + (",video.publish" if tiktok_api.modo() == "direto" else "")
        estado = secrets.token_urlsafe(8)
        print("1. Abra este link logado na conta do TikTok que vai publicar:\n")
        print(tiktok_api.url_de_login(redirect, estado, escopos))
        print(f"\n2. Autorize. A página de retorno vai mostrar o comando com o código (estado: {estado}).")
        print("3. Rode o comando em até 5 minutos.")
        return
    from urllib.parse import unquote
    dados = tiktok_api.trocar_codigo(unquote(args.codigo), redirect)
    print("Login feito. Escopos:", dados.get("scope"))
    print("\nGuarde este valor como secret TIKTOK_REFRESH_TOKEN no GitHub (vale 365 dias):\n")
    print(dados.get("refresh_token"))


def _rascunhos_com_midia(dias: int):
    """Rascunhos cujas imagens ainda podem ser necessárias: os pendentes (sem decisão,
    agendados ou com erro) e os criados nos últimos `dias` dias. Ignora demos e descartados."""
    import json
    from datetime import timezone
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    if not storage.PASTA_RASCUNHOS.exists():
        return
    for arq in sorted(storage.PASTA_RASCUNHOS.glob("*/meta.json")):
        meta = json.loads(arq.read_text(encoding="utf-8"))
        if meta.get("demo") or meta.get("status") == "descartado":
            continue
        recente = datetime.fromisoformat(meta.get("criado_em", "1970-01-01T00:00:00+00:00")) >= limite
        if recente or meta.get("status") != "publicado":
            yield meta["id"], arq.parent


def cmd_midia_site(args) -> None:
    """Copia as imagens 9:16 dos rascunhos recentes para site/midia/<id>/ (vão para o GitHub Pages)."""
    import shutil
    from pathlib import Path
    destino = Path(__file__).resolve().parent / "site" / "midia"
    shutil.rmtree(destino, ignore_errors=True)
    copiados = 0
    for rid, pasta in _rascunhos_com_midia(args.dias):
        imgs = sorted((pasta / "tiktok").glob("slide_*.jpg"))
        if imgs:
            (destino / rid).mkdir(parents=True, exist_ok=True)
            for img in imgs:
                shutil.copy2(img, destino / rid / img.name)
            copiados += 1
    log.info("Imagens 9:16 de %d rascunhos copiadas para %s", copiados, destino)


def cmd_midia_branch(args) -> None:
    """Monta a pasta que vira o branch `midia` (imagens do Instagram e do TikTok, sem histórico)."""
    import shutil
    from pathlib import Path
    destino = Path(args.saida)
    shutil.rmtree(destino, ignore_errors=True)
    n = 0
    for rid, pasta in _rascunhos_com_midia(args.dias):
        imgs = sorted(pasta.glob("slide_*.jpg")) + sorted((pasta / "tiktok").glob("slide_*.jpg"))
        for img in imgs:
            alvo = destino / img.relative_to(storage.PASTA_RASCUNHOS)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img, alvo)
        n += bool(imgs)
    log.info("Mídia de %d rascunhos em %s", n, destino)


def cmd_formatos(args) -> None:
    biblioteca = formatos.carregar()
    notas = formatos.desempenho()
    uso = storage.carregar_estado().get("formatos", {}).get("uso", {})
    print(f"{'formato':28} {'tipo':8} {'usos':>5} {'medidos':>8} {'pontuação média':>16}")
    for f in sorted(biblioteca.values(), key=lambda f: (f["aplica_a"], f["id"])):
        n = notas.get(f["id"], [])
        media = f"{sum(n) / len(n):.1f}" if n else "–"
        print(f"{f['id']:28} {f['aplica_a']:8} {uso.get(f['id'], 0):>5} {len(n):>8} {media:>16}")
    print(f"\nRodízio até cada formato ter {formatos.MIN_AMOSTRA} posts medidos; depois, peso pela pontuação.")
    print("Formatos com erro aparecem como aviso acima e ficam fora do rodízio.")


def cmd_demo(args) -> None:
    estado = storage.carregar_estado()
    if args.modelo == "fria":
        from bot.demo import bancada_exemplo
        item = frias.carregar_fila()[0] if not args.bancada else bancada_exemplo()
        gerar_fria(estado, item=item, demo=True, enviar=args.telegram, formato_id=args.formato)
    elif args.modelo == "semana":
        from bot.demo import semana_exemplo
        gerar_voto_semana(semana_exemplo(), "camara", date(2026, 10, 9), estado, nome=args.parlamentar,
                          demo=True, enviar=args.telegram, forcar=True)
    else:
        from bot.demo import votacao_exemplo
        v = votacao_exemplo(apertado=bool(args.formato and "apertado" in args.formato))
        criar_rascunho(v, estado, demo=True, enviar=args.telegram, formato_id=args.formato)
    storage.salvar_estado(estado)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Como Vota — bot publicador")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gerar")
    g.add_argument("--inicio", help="AAAA-MM-DD (padrão: hoje menos --janela dias)")
    g.add_argument("--fim", help="AAAA-MM-DD (padrão: hoje)")
    g.add_argument("--janela", type=int, default=int(os.getenv("JANELA_DIAS") or 3),
                   help="quantos dias para trás olhar (pega dados publicados com atraso)")
    g.add_argument("--intervalo-proposicao", type=int, default=int(os.getenv("INTERVALO_PROPOSICAO_DIAS") or 7),
                   help="não posta a mesma proposição de novo dentro desse prazo")
    g.add_argument("--casas", default=os.getenv("CASAS") or "camara,senado")
    g.add_argument("--max", type=int, default=int(os.getenv("MAX_POSTS") or 2),
                   help="máximo de posts gerados por execução (por dia)")
    g.add_argument("--dias-sem-post", type=int, default=int(os.getenv("DIAS_SEM_POST_PARA_FRIA") or 3),
                   help="gera pauta fria se ficar esse número de dias sem post (0 desliga)")
    g.add_argument("--sem-telegram", action="store_true")
    g.set_defaults(func=cmd_gerar)

    fr = sub.add_parser("fria", help="gera uma pauta fria agora")
    fr.add_argument("--arquivo", help="explicador específico (nome do arquivo em pautas_frias/)")
    fr.add_argument("--uf", help="Bancada do Estado de uma UF específica (ex.: MT)")
    fr.add_argument("--sem-telegram", action="store_true")
    fr.set_defaults(func=cmd_fria)

    sub.add_parser("verificar").set_defaults(func=cmd_verificar)
    sub.add_parser("fixados", help="gera os 3 posts fixados de conversão").set_defaults(func=cmd_fixados)
    sub.add_parser("formatos", help="lista os formatos e o desempenho de cada um").set_defaults(func=cmd_formatos)
    sub.add_parser("metricas", help="atualiza as métricas do Instagram").set_defaults(func=cmd_metricas)
    sub.add_parser("token-instagram", help="confere e renova o token do Instagram").set_defaults(func=cmd_token_instagram)
    rl = sub.add_parser("relatorio", help="resumo da semana no Telegram")
    rl.add_argument("--se-segunda", action="store_true", help="só manda se hoje for segunda-feira")
    rl.set_defaults(func=cmd_relatorio)
    dg = sub.add_parser("diagnostico", help="confere toda a configuração")
    dg.add_argument("--telegram", action="store_true", help="também manda o resultado no Telegram")
    dg.set_defaults(func=cmd_diagnostico)
    tl = sub.add_parser("tiktok-login", help="login do TikTok (uma vez)")
    tl.add_argument("--codigo", help="código mostrado na página de retorno do login")
    tl.set_defaults(func=cmd_tiktok_login)
    ms = sub.add_parser("midia-site", help="copia as imagens 9:16 recentes para site/midia")
    ms.add_argument("--dias", type=int, default=14)
    ms.set_defaults(func=cmd_midia_site)
    mb = sub.add_parser("midia-branch", help="monta a pasta do branch midia (usado pelos workflows)")
    mb.add_argument("--saida", default="_midia")
    mb.add_argument("--dias", type=int, default=21)
    mb.set_defaults(func=cmd_midia_branch)
    rp = sub.add_parser("repost", help="gera o repost do explicador com melhor desempenho")
    rp.add_argument("--base", help="um explicador específico (ex.: 05-veto)")
    rp.add_argument("--sem-telegram", action="store_true")
    rp.set_defaults(func=cmd_repost)

    qz = sub.add_parser("quiz", help='exporta site/quiz.json para o teste "Quem vota como você?"')
    qz.add_argument("--demo", action="store_true", help="usa perguntas e parlamentares fictícios")
    qz.set_defaults(func=cmd_quiz)

    se = sub.add_parser("semana", help='gera o post "Voto da Semana"')
    se.add_argument("--fim", help="AAAA-MM-DD, último dia da semana (padrão: hoje)")
    se.add_argument("--casas", default=os.getenv("CASAS_SEMANA") or "camara",
                    help="camara, senado ou camara,senado (um post por casa)")
    se.add_argument("--parlamentar", help="escolhe manualmente pelo nome (padrão: rodízio automático)")
    se.add_argument("--forcar", action="store_true", help="gera de novo mesmo se a semana já tiver post")
    se.add_argument("--sem-telegram", action="store_true")
    se.set_defaults(func=cmd_semana)

    rf = sub.add_parser("refazer", help="gera de novo rascunhos não aprovados (mesmo formato)")
    rf.add_argument("ids", nargs="*", help="ids dos rascunhos (ex.: senado-7107 camara-2236186-60)")
    rf.add_argument("--explicados", action="store_true",
                    help="também refaz os que ganharam texto novo no explicacoes.yaml")
    rf.add_argument("--sem-telegram", action="store_true")
    rf.set_defaults(func=cmd_refazer)

    co = sub.add_parser("consultar", help="pergunta livre ao Gemini; a resposta vai para o Telegram")
    co.add_argument("pergunta", nargs="?", help="padrão: como deixar os posts mais interessantes")
    co.set_defaults(func=cmd_consultar)

    sub.add_parser("pendentes", help="votações em rascunho que ainda não têm texto no explicacoes.yaml"
                   ).set_defaults(func=cmd_pendentes)

    pub = sub.add_parser("publicar")
    pub.add_argument("id")
    pub.set_defaults(func=cmd_publicar)

    d = sub.add_parser("demo")
    d.add_argument("--telegram", action="store_true", help="também envia para o Telegram")
    d.add_argument("--modelo", choices=["carrossel", "semana", "fria"], default="carrossel")
    d.add_argument("--bancada", action="store_true", help="(modelo fria) usa a Bancada do Estado fictícia")
    d.add_argument("--parlamentar", help="(modelo semana) nome fictício a destacar")
    d.add_argument("--formato", help="força um formato da biblioteca (ex.: votacao-pergunta)")
    d.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
