/**
 * Contador anônimo do teste "Quem vota como você?" — Cloudflare Worker + KV.
 *
 * O QUE GUARDA: só totais. Ex.: "q3:S" = 1.204 pessoas responderam SIM na pergunta 3;
 * "partido:camara:XYZ" = 310 testes terminaram com maior afinidade com o partido XYZ.
 * O QUE NÃO GUARDA: IP, cookie, ID, data/hora individual, nem a sequência de respostas
 * de uma pessoa. Cada envio vira +1 em alguns contadores e é descartado.
 *
 * Como publicar (gratuito no plano free da Cloudflare):
 *   1. npm create cloudflare@latest contador  (ou cole este arquivo no painel Workers)
 *   2. Crie um namespace KV e ligue ao Worker com o nome CONTADORES
 *   3. Defina a variável ORIGEM_PERMITIDA = https://SEU_USUARIO.github.io (ou seu domínio)
 *   4. Coloque a URL do Worker em CONFIG.contadorUrl no site/index.html
 *   5. Desligue o "Logpush"/logs persistentes do Worker para não reter IPs
 *
 * Rotas:
 *   POST /      corpo {versao, respostas:{q1:"S"|"N"|"P"}, partidos:{camara:"X", senado:"Y"}}
 *   GET  /totais  devolve todos os contadores (para o bot montar posts com estatísticas)
 *
 * Observação: o KV não é transacional; em picos simultâneos algum +1 pode se perder.
 * Para estatística de engajamento isso é aceitável. Se precisar de exatidão, troque por
 * Durable Objects ou D1.
 */
const ID = /^q\d{1,3}$/;
const VOTO = /^[SNP]$/;
const SIGLA = /^[A-Za-zÀ-ú0-9 ]{1,20}$/;

export default {
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ORIGEM_PERMITIDA || "*",
      "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };
    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/totais") {
      const totais = {};
      let cursor;
      do {
        const pagina = await env.CONTADORES.list({ cursor });
        for (const k of pagina.keys) totais[k.name] = Number(await env.CONTADORES.get(k.name)) || 0;
        cursor = pagina.list_complete ? undefined : pagina.cursor;
      } while (cursor);
      return Response.json(totais, { headers: cors });
    }

    if (req.method !== "POST") return new Response("Método não permitido", { status: 405, headers: cors });

    let corpo;
    try { corpo = await req.json(); } catch { return new Response("JSON inválido", { status: 400, headers: cors }); }
    const respostas = corpo && typeof corpo.respostas === "object" ? corpo.respostas : {};
    const chaves = ["testes"];
    for (const [q, r] of Object.entries(respostas).slice(0, 60)) {
      if (ID.test(q) && VOTO.test(r)) chaves.push(`${q}:${r}`);
    }
    for (const [casa, sigla] of Object.entries(corpo.partidos || {})) {
      if ((casa === "camara" || casa === "senado") && SIGLA.test(sigla || "")) chaves.push(`partido:${casa}:${sigla}`);
    }
    await Promise.all(chaves.map(async k => {
      const atual = Number(await env.CONTADORES.get(k)) || 0;
      await env.CONTADORES.put(k, String(atual + 1));
    }));
    return new Response(null, { status: 204, headers: cors });
  },
};
