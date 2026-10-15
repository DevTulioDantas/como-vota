"""Testes offline: simulam as respostas das APIs (sem internet).

Rode com:  python -m pytest -q   (ou  python tests/test_pipeline.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import selector  # noqa: E402
from bot.collectors import camara, senado  # noqa: E402
from bot.models import NAO, SIM  # noqa: E402


def _fake_camara(url, params=None, tentativas=4):
    if url.endswith("/votacoes"):
        return {"dados": [
            {"id": "100-1", "data": "2026-10-07", "descricao": "Aprovado o texto-base do Substitutivo.", "aprovacao": 1, "uri": "u1"},
            {"id": "100-2", "data": "2026-10-07", "descricao": "Aprovado requerimento de urgência.", "aprovacao": 1, "uri": "u2"},
            {"id": "100-3", "data": "2026-10-07", "descricao": "Aprovada em votação simbólica.", "aprovacao": 1, "uri": "u3"},
        ], "links": []}
    if url.endswith("/votos"):
        if "100-3" in url:
            return {"dados": []}
        votos = [{"tipoVoto": "Sim", "deputado_": {"nome": f"Dep {i}", "siglaPartido": "PX" if i % 2 else "PY", "siglaUf": "SP"}} for i in range(260)]
        votos += [{"tipoVoto": "Não", "deputado_": {"nome": f"Dep N{i}", "siglaPartido": "PY", "siglaUf": "RJ"}} for i in range(200)]
        return {"dados": votos}
    if url.endswith("/orientacoes"):
        return {"dados": [
            {"siglaPartidoBloco": "PX", "orientacaoVoto": "Sim"},
            {"siglaPartidoBloco": "PY", "orientacaoVoto": "Não"},
            {"siglaPartidoBloco": "Governo", "orientacaoVoto": "Sim"},
        ]}
    return {"dados": {"proposicoesAfetadas": [
        {"id": 999, "siglaTipo": "REQ", "numero": 1, "ano": 2026, "ementa": "req"},
        {"id": 123, "siglaTipo": "PL", "numero": 42, "ano": 2026, "ementa": "Dispõe sobre algo."},
    ]}}


def test_camara_e_seletor(monkeypatch=None):
    camara._get = _fake_camara
    senado._get = lambda *a, **k: [{"apelido": ""}]  # busca do apelido no Senado, sem internet
    vs = camara.coletar("2026-10-01", "2026-10-08")
    assert len(vs) == 2, "votação simbólica deve ser descartada"
    v = vs[0]
    assert v.proposicao == "PL 42/2026" and v.orientacao_governo == "Sim"
    assert v.placar()[SIM] == 260 and v.placar()[NAO] == 200
    # PY orientou Não, mas 130 deputados do PY votaram Sim
    assert len(v.dissidentes()) == 130
    escolhidas = selector.selecionar(vs)
    assert len(escolhidas) == 1 and "texto-base" in escolhidas[0].descricao


def test_senado_secreta_descartada():
    def fake(url, params=None, tentativas=4):
        base = {"sigla": "PLP", "numero": "74", "ano": 2026, "identificacao": "PLP 74/2026",
                "ementa": "Ementa.", "dataSessao": "2026-10-08", "resultadoVotacao": "A", "codigoMateria": 1}
        votos = [{"nomeParlamentar": f"S{i}", "siglaPartidoParlamentar": "PZ", "siglaUFParlamentar": "MT",
                  "siglaVotoParlamentar": "Sim" if i < 50 else "Não"} for i in range(70)]
        return [
            {**base, "codigoSessaoVotacao": 1, "votacaoSecreta": "N", "votos": votos},
            {**base, "codigoSessaoVotacao": 2, "votacaoSecreta": "S", "identificacao": "MSF 1/2026",
             "votos": [{**x, "siglaVotoParlamentar": "Votou"} for x in votos]},
        ]
    senado._get = fake
    vs = senado.coletar("2026-10-01", "2026-10-08")
    assert len(vs) == 2
    escolhidas = selector.selecionar(vs)
    assert [v.id for v in escolhidas] == ["senado-1"]


def test_voto_da_semana():
    from bot import semana
    from bot.demo import semana_exemplo
    pautas = semana_exemplo()
    alvo = pautas[0][0].votos[0]
    pautas[1][0].votos = [v for v in pautas[1][0].votos if v.id != alvo.id]  # ausente na 2a pauta
    dados = semana.montar(pautas, alvo, __import__("datetime").date(2026, 10, 9))
    assert dados["itens"][1]["rotulo"] == semana.AUSENTE
    assert semana.escolher(pautas, [], "x", nome="nome que não existe") is None
    # rodízio: ninguém repete antes de todos os elegíveis aparecerem
    pool, hist = semana.candidatos(pautas), []
    for n in range(len(pool)):
        hist.append(semana.chave(semana.escolher(pautas, hist, f"s{n}")))
    assert len(set(hist)) == len(pool)


def test_pautas_frias():
    from datetime import date
    from bot import frias
    fila = frias.carregar_fila()  # valida todos os YAML da pasta
    assert len(fila) >= 1 and all(len(i["slides"]) <= frias.MAX_SLIDES_CONTEUDO for i in fila)
    deps = [{"nome": f"Dep {i:02d}", "partido": "PX" if i % 3 else "PY"} for i in range(70)]
    b = frias.montar_bancada("SP", deps, date(2026, 10, 13))
    assert len(b["slides"]) + 2 <= 10, "carrossel não pode passar de 10 slides"
    estado = {"rascunhos": {}}
    item, _ = frias.escolher(estado, coletar_bancada=lambda uf: b)
    assert item["fonte_tipo"] == "explicador"
    frias.registrar_uso(estado, item)
    item2, _ = frias.escolher(estado, coletar_bancada=lambda uf: b)
    assert item2["fonte_tipo"] == "bancada"


def test_quiz_export():
    from bot import quiz
    d = quiz.exportar_demo()
    assert {q["casa"] for q in d["perguntas"]} == {"camara", "senado"}
    casa_q = {q["id"]: q["casa"] for q in d["perguntas"]}
    for p in d["parlamentares"]:
        assert set(p["votos"].values()) <= {"S", "N", "A", "O", "X"}
        # parlamentar só tem voto em perguntas da própria Casa
        assert all(casa_q[q] == p["casa"] for q in p["votos"])


def test_formatos():
    from bot import formatos
    from bot.demo import votacao_exemplo
    from bot.render.renderer import contexto
    biblioteca = formatos.carregar()
    assert {"votacao-classico", "votacao-apertado", "fria-classico"} <= set(biblioteca)
    # neutralidade: gancho sensacionalista é recusado
    ruim = {"id": "x", "aplica_a": "votacao", "sequencia": ["capa", "final"], "legenda_gancho": "Que vergonha: {titulo}"}
    try:
        formatos.validar(ruim)
        assert False, "deveria recusar"
    except ValueError as e:
        assert "vergonh" in str(e)
    # condição: placar apertado só entra em votação apertada
    folgada, apertada = votacao_exemplo(), votacao_exemplo(apertado=True)
    elegiveis = lambda v: {f["id"] for f in biblioteca.values() if f["aplica_a"] == "votacao"
                           and formatos._elegivel(f, formatos.info_votacao(v))}
    assert "votacao-apertado" not in elegiveis(folgada) and "votacao-apertado" in elegiveis(apertada)
    # fase de teste: rodízio pelo menos usado
    estado = {"formatos": {"uso": {"votacao-classico": 3, "votacao-pergunta": 1, "votacao-placar-na-capa": 2,
                                   "votacao-mapa": 2}}}
    f = formatos.escolher("votacao", estado, formatos.info_votacao(folgada), formatos=biblioteca, notas={})
    assert f["id"] == "votacao-pergunta"
    # com amostra suficiente: o de melhor pontuação sai mais vezes
    notas = {"votacao-classico": [10] * 3, "votacao-pergunta": [80] * 3, "votacao-placar-na-capa": [10] * 3,
             "votacao-mapa": [10] * 3}
    vezes = sum(formatos.escolher("votacao", {}, formatos.info_votacao(folgada), semente=str(i),
                                  formatos=biblioteca, notas=notas)["id"] == "votacao-pergunta" for i in range(200))
    assert vezes > 120
    # sequência: capa sem ementa ganha o "entenda"; cta some sem site
    ctx = contexto(folgada, {"titulo": "T", "resumo": "R", "resultado": "APROVADA"}, "@x",
                   formato=biblioteca["votacao-pergunta"])
    assert ctx["slides"] == ["capa", "entenda", "placar", "partidos", "dissidentes", "final"]
    # gancho da legenda
    leg = formatos.aplicar_gancho("🗳️ velho\nresto", biblioteca["votacao-apertado"],
                                  formatos.variaveis_votacao(apertada, {"titulo": "Título X", "resultado": "REJEITADA"}))
    assert leg.startswith("Decidido por 4 votos na Câmara: Título X") and leg.endswith("resto")


def test_tiktok_legenda():
    from bot.tiktok import HASHTAGS, legenda_tiktok
    leg = legenda_tiktok("Gancho\n\nTexto\n\n#ComoVotaDeputado #VotoAberto")
    assert leg == f"Gancho\n\nTexto\n\n{HASHTAGS}"
    assert len(legenda_tiktok("x\n" * 2000)) < 1100


def test_metricas_e_repost():
    from datetime import datetime, timedelta, timezone
    from bot import frias, metricas
    assert metricas.pontuar({"reach": 1000, "saved": 10, "shares": 5, "comments": 2, "likes": 40}) == 67.0
    assert metricas.pontuar({"reach": 0}) is None
    agora = datetime.now(timezone.utc)
    def meta(base, dias, pont, alcance=500, fonte="explicador"):
        return {"id": base if fonte == "explicador" else base + "-r2", "base_id": base, "tipo": "fria",
                "fonte_tipo": fonte, "status": "publicado", "item": {"id": base, "titulo": base, "slides": []},
                "historico": [{"status": "publicado", "em": (agora - timedelta(days=dias)).isoformat()}],
                "metricas": {"pontuacao": pont, "reach": alcance, "saved": 9, "shares": 3}}
    metas = [meta("fria-a", 90, 50), meta("fria-b", 90, 10), meta("fria-c", 90, 12), meta("fria-d", 90, 8),
             meta("fria-e", 20, 70), meta("fria-f", 90, 99, alcance=30)]
    estado = {}
    cands = frias.candidatos_repost(estado, agora=agora, metas=metas)
    # fria-e é a melhor, mas saiu há 20 dias; fria-f tem alcance baixo demais
    assert [g["base_id"] for g in cands] == ["fria-a"]
    # poucos medidos: ninguém é candidato
    assert frias.candidatos_repost({}, agora=agora, metas=metas[:3]) == []
    # rodízio explicador → bancada → repost
    b = {"id": "fria-bancada-sp-x", "fonte_tipo": "bancada", "titulo": "B", "slides": []}
    estado = {"frias": {"ultima_fonte": "bancada", "usadas": [], "ufs_feitas": [], "reposts": {}}}
    item, _ = frias.escolher(estado, coletar_bancada=lambda uf: b, candidatos=cands)
    assert item["fonte_tipo"] == "repost" and item["base_id"] == "fria-a" and item["id"] == "fria-a-r2"
    frias.registrar_uso(estado, item)
    assert "fria-a" in estado["frias"]["reposts"]
    # depois de gerado, não volta a ser candidato até passar o prazo
    assert frias.candidatos_repost(estado, agora=agora, metas=metas) == []


class _FakeTikTok:
    """Imita a API do TikTok: registra as chamadas e responde como a documentação."""
    def __init__(self, opcoes=("SELF_ONLY",), status_url=200, novo_refresh="refresh-2"):
        self.chamadas, self.opcoes, self.status_url, self.novo_refresh = [], list(opcoes), status_url, novo_refresh

    class R:
        def __init__(self, corpo, status=200):
            self.corpo, self.status_code = corpo, status
        def json(self):
            return self.corpo

    def post(self, url, json=None, data=None, headers=None, timeout=None):
        caminho = url.split("/v2", 1)[1]
        self.chamadas.append((caminho, json if json is not None else data))
        ok = {"code": "ok", "message": ""}
        if caminho == "/oauth/token/":
            return self.R({"access_token": "acc", "expires_in": 86400, "refresh_token": self.novo_refresh})
        if caminho == "/post/publish/creator_info/query/":
            return self.R({"data": {"privacy_level_options": self.opcoes}, "error": ok})
        if caminho == "/post/publish/content/init/":
            return self.R({"data": {"publish_id": "p_123"}, "error": ok})
        if caminho == "/post/publish/status/fetch/":
            final = "SEND_TO_USER_INBOX" if self.chamadas[-2][1].get("post_mode") == "MEDIA_UPLOAD" else "PUBLISH_COMPLETE"
            return self.R({"data": {"status": final}, "error": ok})
        raise AssertionError(caminho)

    def head(self, url, timeout=None, allow_redirects=None):
        return self.R({}, self.status_url)


def _ambiente_tiktok(tmp, modo):
    import os
    from bot import tiktok_api
    os.environ.update(TIKTOK_MODO=modo, TIKTOK_CLIENT_KEY="k", TIKTOK_CLIENT_SECRET="s",
                      TIKTOK_REFRESH_TOKEN="refresh-1", TIKTOK_MIDIA_URL="https://site.exemplo/midia",
                      TIKTOK_REFRESH_TOKEN_SAIDA=str(tmp / "novo_token"))
    os.environ.pop("DRY_RUN", None)
    os.environ.pop("TIKTOK_PRIVACIDADE", None)
    tiktok_api._token_cache.clear()
    tiktok_api._dormir = lambda s: None
    return tiktok_api


def test_tiktok_api():
    import os
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())

    # modo rascunho: vai para a caixa de entrada, sem privacidade, e guarda o token novo
    api = _ambiente_tiktok(tmp, "rascunho")
    api._http = fake = _FakeTikTok()
    urls = api.urls_midia("camara-1", [Path("slide_01.jpg"), Path("slide_02.jpg")])
    assert urls[0] == "https://site.exemplo/midia/camara-1/slide_01.jpg"
    res = api.publicar(urls, "Gancho 🗳️\n\nTexto\n\n#tag")
    init = next(c[1] for c in fake.chamadas if c[0] == "/post/publish/content/init/")
    assert init["post_mode"] == "MEDIA_UPLOAD" and init["media_type"] == "PHOTO"
    assert init["source_info"] == {"source": "PULL_FROM_URL", "photo_images": urls, "photo_cover_index": 0}
    assert "privacy_level" not in init["post_info"] and init["post_info"]["title"] == "Gancho 🗳️"
    assert res["status"] == "SEND_TO_USER_INBOX"
    assert (tmp / "novo_token").read_text() == "refresh-2" and os.environ["TIKTOK_REFRESH_TOKEN"] == "refresh-2"

    # modo direto: consulta a conta e respeita as opções de privacidade
    api = _ambiente_tiktok(tmp, "direto")
    api._http = fake = _FakeTikTok(opcoes=["SELF_ONLY"])
    res = api.publicar(urls, "Gancho")
    init = next(c[1] for c in fake.chamadas if c[0] == "/post/publish/content/init/")
    assert init["post_mode"] == "DIRECT_POST" and init["post_info"]["privacy_level"] == "SELF_ONLY"
    assert res["status"] == "PUBLISH_COMPLETE"
    os.environ["TIKTOK_PRIVACIDADE"] = "PUBLIC_TO_EVERYONE"
    try:
        api.publicar(urls, "Gancho")
        assert False, "deveria recusar privacidade não permitida"
    except api.ErroTikTok as e:
        assert "não permitida" in str(e)

    # imagens ainda não publicadas no site
    api = _ambiente_tiktok(tmp, "rascunho")
    api._http = _FakeTikTok(status_url=404)
    try:
        api.publicar(urls, "x")
        assert False
    except api.ImagemForaDoAr:
        pass
    # título respeita o limite em unidades UTF-16 (emoji conta 2)
    assert len(api._cortar("🗳️" * 100, 90)) <= 90
    for n in ("TIKTOK_MODO", "TIKTOK_PRIVACIDADE", "TIKTOK_REFRESH_TOKEN_SAIDA"):
        os.environ.pop(n, None)


def test_agenda():
    import os
    from datetime import datetime
    from bot import agenda
    os.environ.pop("HORARIOS_PUBLICACAO", None)
    F = agenda.FUSO
    agora = datetime(2026, 10, 14, 10, 0, tzinfo=F)          # quarta, 10h
    s1 = agenda.proximo_horario([], agora)
    assert s1 == datetime(2026, 10, 14, 11, 45, tzinfo=F)
    s2 = agenda.proximo_horario([s1], agora)                 # um post por horário
    assert s2 == datetime(2026, 10, 14, 18, 45, tzinfo=F)
    s3 = agenda.proximo_horario([s1, s2], agora)             # vira o dia
    assert s3 == datetime(2026, 10, 15, 11, 45, tzinfo=F)
    assert agenda.descrever(s1, agora) == "hoje às 11:45" and agenda.descrever(s3, agora) == "amanhã às 11:45"
    assert agenda.descrever(datetime(2026, 10, 17, 18, 45, tzinfo=F), agora) == "sáb 17/10 às 18:45"
    metas = [{"id": "a", "status": "agendado", "agendado_para": s2.isoformat()},
             {"id": "b", "status": "agendado", "agendado_para": s1.isoformat()},
             {"id": "c", "status": "enviado"}]
    assert agenda.vencidos(metas, datetime(2026, 10, 14, 12, 0, tzinfo=F)) == ["b"]
    assert agenda.vencidos(metas, datetime(2026, 10, 14, 19, 0, tzinfo=F)) == ["b", "a"]
    os.environ["HORARIOS_PUBLICACAO"] = "imediato"
    assert agenda.horarios() == [] and agenda.proximo_horario([], agora) is None
    os.environ["HORARIOS_PUBLICACAO"] = "19:00, 8:30"
    assert [h.strftime("%H:%M") for h in agenda.horarios()] == ["08:30", "19:00"]
    os.environ.pop("HORARIOS_PUBLICACAO")


def test_token_instagram():
    import os
    import tempfile
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from bot import publisher, token_ig
    saida = Path(tempfile.mkdtemp()) / "tok"
    os.environ.update(IG_USER_ID="1", IG_ACCESS_TOKEN="velho", IG_GRAPH_BASE="https://graph.instagram.com/v23.0",
                      IG_ACCESS_TOKEN_SAIDA=str(saida))
    original = publisher._chamar
    publisher._chamar = lambda metodo, url, **p: {"username": "comovota", "followers_count": 1234}

    class R:
        status_code = 200
        def json(self):
            return {"access_token": "novo", "token_type": "bearer", "expires_in": 5184000}
    token_ig._http = type("H", (), {"get": staticmethod(lambda *a, **k: R())})
    estado, agora = {}, datetime(2026, 10, 14, tzinfo=timezone.utc)
    ok, msg = token_ig.manter(estado, agora)
    assert ok and "renovado" in msg and saida.read_text() == "novo"
    assert estado["instagram"]["seguidores"]["2026-10-14"] == 1234
    ok, msg = token_ig.manter(estado, agora + timedelta(days=2))     # renovou há 2 dias: só confere
    assert ok and msg == "token válido"
    publisher._chamar = lambda *a, **k: (_ for _ in ()).throw(publisher.ErroPublicacao("token expirado"))
    ok, msg = token_ig.manter(estado, agora + timedelta(days=9))
    assert not ok and "IG_ACCESS_TOKEN" in msg
    publisher._chamar = original
    for n in ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_GRAPH_BASE", "IG_ACCESS_TOKEN_SAIDA"):
        os.environ.pop(n)


def test_relatorio():
    from datetime import datetime, timedelta, timezone
    from bot import relatorio
    agora = datetime(2026, 10, 19, 9, tzinfo=timezone.utc)
    def m(i, tipo, dias, status="publicado", fonte=None):
        return {"id": f"p{i}", "tipo": tipo, "fonte_tipo": fonte, "status": status,
                "historico": [{"status": status, "em": (agora - timedelta(days=dias)).isoformat()}]}
    metas = [m(1, None, 2), m(2, "fria", 3, fonte="explicador"), m(3, None, 20), m(4, None, 1, "enviado")]
    estado = {"instagram": {"seguidores": {"2026-10-12": 100, "2026-10-19": 130}}}
    txt = relatorio.montar(estado, metas, agora)
    assert "2 posts no Instagram: 1 votação, 1 explicador" in txt
    assert "130 seguidores (+30 na semana)" in txt and "1 rascunho esperando sua aprovação" in txt


def test_quorum_qualidade_mapa():
    import dataclasses
    from bot import formatos, qualidade
    from bot.demo import votacao_exemplo
    from bot.models import Voto
    from bot.render.renderer import GRADE_UF, _estados
    base = votacao_exemplo()
    votos = ([Voto(f"S{i}", "PAA", "SP", "Sim", id=f"s{i}") for i in range(300)]
             + [Voto(f"N{i}", "PBB", "AC", "Não", id=f"n{i}") for i in range(10)])
    pec = dataclasses.replace(base, tipo_proposicao="PEC", descricao="PEC em primeiro turno", votos=votos, aprovada=False)
    assert pec.quorum() == (308, "3 em cada 5 dos 513 deputados")
    assert dataclasses.replace(pec, descricao="Rejeitado o destaque 3").quorum() is None
    assert dataclasses.replace(pec, casa="senado").quorum()[0] == 49
    assert dataclasses.replace(pec, tipo_proposicao="PL").quorum() is None
    v = formatos.variaveis_votacao(pec, {"titulo": "T"})
    assert v["quorum"] == 308 and v["diferenca"] == 8 and "eram necessários 308" in v["decisao_txt"]
    # PEC com 300 SIM rejeitada é coerente: nenhum alerta sobre resultado
    assert not any("resultado" in a for a in qualidade.checar(pec))
    # aprovada com 300 SIM numa PEC não é: alerta
    assert any("quórum" in a for a in qualidade.checar(dataclasses.replace(pec, aprovada=True)))
    # totais oficiais diferentes e parlamentar repetido
    alertas = qualidade.checar(dataclasses.replace(pec, votos=votos + votos[:1], totais_oficiais={"Sim": 280}))
    assert any("total oficial" in a for a in alertas) and any("mais de uma vez" in a for a in alertas)
    # mapa: 27 UFs, contagem por estado
    assert len(GRADE_UF) == 27 and len(set(GRADE_UF.values())) == 27
    est = _estados(pec)
    sp = next(t for t in est["tiles"] if t["uf"] == "SP")
    assert sp["texto"] == "300×0" and est["maioria"] == {"sim": 1, "nao": 1, "empate": 0}


def test_orientacao_federacao_e_bloco():
    """Formato real da Câmara: federações com hífen e prefixo "Fdr", blocos com "Bl"."""
    from bot.models import Votacao
    v = Votacao(id="x", casa="camara", data="", proposicao="", tipo_proposicao="", ementa="",
                descricao="", aprovada=True, url_fonte="",
                orientacoes={"Fdr PT-PCdoB-PV": "Não", "Fdr PSOL-REDE": "Sim", "Bl PP/União": "Sim", "PL": "Sim"})
    assert v.orientacao_do_partido("PCdoB") == "Não" and v.orientacao_do_partido("PT") == "Não"
    assert v.orientacao_do_partido("REDE") == "Sim" and v.orientacao_do_partido("União") == "Sim"
    assert v.orientacao_do_partido("PL") == "Sim" and v.orientacao_do_partido("NOVO") is None


def test_totais_do_texto():
    """Placar oficial escrito pela Câmara (descrição) e pelo Senado (informe legislativo)."""
    from bot.models import ABSTENCAO, totais_do_texto
    assert totais_do_texto("Aprovada, em segundo turno, a PEC. Sim: 368; Não: 96; Abstenção: 7; Total: 471.")         == {SIM: 368, NAO: 96, ABSTENCAO: 7}
    assert totais_do_texto("Aprovado o projeto, com o seguinte resultado: Sim - 58, Não - 1, Presidente - 1, Total - 60.")         == {SIM: 58, NAO: 1}
    assert totais_do_texto("Aprovado o requerimento. Sim - 50, Não - 9. Aprovado o projeto: Sim - 58, Não - 1.") == {}
    assert totais_do_texto("Aprovado o Requerimento de Urgência.") == {}


def test_titulo_sem_ia():
    """Sem IA, o título pula o preâmbulo jurídico e não termina em palavra solta."""
    from bot.summarizer import titulo_da_ementa
    assert titulo_da_ementa(
        "Altera o art. 7º da Constituição Federal para reduzir a duração máxima semanal do trabalho e prever "
        "2 (dois) dias de repouso semanal remunerado, sem qualquer redução salarial; e dá outras providências."
    ) == "Reduz a duração máxima semanal do trabalho"
    assert titulo_da_ementa(
        "Altera a Lei nº 9.504, de 30 de setembro de 1997, que “Estabelece normas para as eleições”, "
        "para proibir o uso de bandeiras ao longo das vias públicas."
    ).startswith("Proíbe o uso de bandeiras")
    t = titulo_da_ementa("Institui diretrizes nacionais para a prevenção e a gestão de riscos de desastres "
                         "naturais nos municípios brasileiros de pequeno porte.")
    assert len(t) <= 70 and t.endswith("…") and not t.endswith(" de…")
    assert titulo_da_ementa("Institui a Lei Falar é Crescer.") == "Institui a Lei Falar é Crescer"


def test_apelido():
    """Apelido oficial do Senado vira o título; apelidos.yaml manda mais; o alerta pede conferência."""
    from bot import qualidade, summarizer
    from bot.models import Votacao
    pedidos = []

    def fake(url, params=None, tentativas=4):
        pedidos.append(params)
        return [{"apelido": "Fim da escala 6x1"}] if url.endswith("/processo") else []
    senado._get = fake
    senado._apelidos.clear()
    assert senado.apelido_oficial(sigla="PEC", numero=221, ano=2019) == "Fim da escala 6x1"
    assert senado.apelido_oficial(sigla="PEC", numero=221, ano=2019) == "Fim da escala 6x1" and len(pedidos) == 1
    assert senado.apelido_oficial(sigla="PL", numero=1, ano=2015) == "", "antes de 2019 a numeração não é única"

    v = Votacao(id="senado-1", casa="senado", data="2026-10-14", proposicao="PEC 221/2019", tipo_proposicao="PEC",
                ementa="Altera o art. 7º da Constituição Federal para reduzir a duração máxima semanal do trabalho.",
                descricao="", aprovada=True, url_fonte="u", apelido="Fim da escala 6x1", fonte_apelido="Senado")
    summarizer.ARQUIVO_APELIDOS = Path("/nao/existe.yaml")
    textos = summarizer.gerar_textos(v)
    assert textos["titulo"] == "Fim da escala 6x1" and "conhecida como “Fim da escala 6x1”" in textos["legenda"]
    assert any("apelido" in a for a in qualidade.checar(v))

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        arq = Path(d) / "apelidos.yaml"
        arq.write_text('"PEC 221/2019": "Escala 6x1"', encoding="utf-8")
        summarizer.ARQUIVO_APELIDOS = arq
        assert summarizer.gerar_textos(v)["titulo"] == "Escala 6x1" and v.fonte_apelido == "curadoria"


def test_partidos_separa_abstencao_e_nao_votou():
    """No gráfico por partido, abstenção é voto registrado e "não votou" (licença, missão) é outra coisa."""
    from bot.models import Votacao, Voto
    votos = [Voto(nome=f"S{i}", partido="PL", uf="SP", voto=SIM) for i in range(12)]
    votos += [Voto(nome="A", partido="PL", uf="SP", voto="Abstenção"), Voto(nome="O", partido="PL", uf="RJ", voto="Obstrução")]
    votos += [Voto(nome=f"L{i}", partido="PL", uf="MG", voto="Outro", voto_original="Licença saúde") for i in range(3)]
    v = Votacao(id="x", casa="senado", data="", proposicao="", tipo_proposicao="", ementa="", descricao="",
                aprovada=True, url_fonte="", votos=votos)
    pl = v.por_partido()[0]
    assert (pl["sim"], pl["abstencao"], pl["nao_votou"], pl["outros"]) == (12, 2, 3, 5)


def test_slide_entenda():
    """Capa sem ementa ganha o slide "O que está em votação", com tipo e etapa explicados."""
    from bot import entenda
    from bot.models import Votacao
    from bot.render import renderer
    v = Votacao(id="x", casa="camara", data="2026-10-14", proposicao="PLP 281/2019", tipo_proposicao="PLP",
                ementa="Dispõe sobre os regimes de resolução das instituições autorizadas a funcionar pelo Banco Central.",
                descricao="Rejeitada a Subemenda Substitutiva ao Projeto de Lei Complementar nº 281, de 2019.",
                aprovada=False, url_fonte="u")
    etapa, so_etapa = entenda.explicar_etapa(v)
    assert "nova versão do texto, escrita pelo relator" in etapa and so_etapa
    v.descricao = "Aprovado o texto-base do Substitutivo."
    assert "texto principal" in entenda.explicar_etapa(v)[0] and not entenda.explicar_etapa(v)[1]
    assert entenda.explicar_tipo(v).startswith("Projeto de Lei Complementar")
    textos = {"titulo": "t", "resumo": v.ementa[:40] + "…", "resultado": "REJEITADA"}
    ctx = renderer.contexto(v, textos, "@x", formato={"capa": "apertado", "sequencia": ["capa", "placar", "final"]})
    assert ctx["slides"][:2] == ["capa", "entenda"] and ctx["entenda_texto"] == v.ementa
    ctx = renderer.contexto(v, textos, "@x", formato={"capa": "classico", "sequencia": ["capa", "placar", "final"]})
    assert "entenda" not in ctx["slides"], "a capa clássica já mostra a ementa"
    # carimbo: o substitutivo caiu, não o projeto
    v.descricao = "Rejeitada a Subemenda Substitutiva ao Projeto de Lei Complementar nº 281, de 2019."
    assert entenda.carimbo(v) == "SUBSTITUTIVO REJEITADO"
    v.descricao, v.aprovada = "Aprovada a Emenda Aglutinativa nº 1.", True
    assert entenda.carimbo(v) == "EMENDA APROVADA"
    v.descricao = "Aprovado o texto-base do Substitutivo."
    assert entenda.carimbo(v) == "", "texto-base usa o carimbo normal"


if __name__ == "__main__":
    test_camara_e_seletor()
    test_senado_secreta_descartada()
    test_voto_da_semana()
    test_pautas_frias()
    test_quiz_export()
    test_formatos()
    test_tiktok_legenda()
    test_metricas_e_repost()
    test_tiktok_api()
    test_agenda()
    test_token_instagram()
    test_relatorio()
    test_quorum_qualidade_mapa()
    test_orientacao_federacao_e_bloco()
    test_totais_do_texto()
    test_titulo_sem_ia()
    test_apelido()
    test_partidos_separa_abstencao_e_nao_votou()
    test_slide_entenda()
    print("ok")
