# CXTV Brasil — Regionais V9 para SS IPTV

Gerador automático de M3U baseado nas fontes oficiais fornecidas pelo usuário para a CXTV Brasil.

## Fontes

As URLs ficam centralizadas em `fontes_estados.json`. A lista inclui a página Brasil e 20 páginas estaduais fornecidas para este projeto.

## Como funciona

1. Tenta ler diretamente cada página.
2. Se a CXTV responder 403, tenta o Jina Reader com navegador.
3. Quando a página estadual entregar apenas a primeira leva de canais, usa busca por páginas individuais da CXTV para completar a descoberta.
4. Mantém um diagnóstico incremental em `descobertos.json` desde o primeiro passo.
5. Abre cada página individual do canal com Chromium e captura o stream HLS.
6. Testa o manifesto HLS e segmentos antes de colocar o canal na M3U.
7. Gera nomes, categorias, `tvg-name`, país BR e idioma Português.
8. Atualiza automaticamente a cada 6 horas.

## Arquivos principais

- `fontes_estados.json` — URLs utilizadas.
- `gerar_m3u.py` — gerador.
- `.github/workflows/atualizar.yml` — GitHub Actions.
- `cxtvbrasil.m3u` — lista final para SS IPTV.
- `descobertos.json` — diagnóstico da descoberta.
- `status.json` — resumo da execução.

## Importante

A CXTV apresenta atualmente quantidades diferentes por estado e algumas páginas usam carregamento adicional por botão. Por isso o projeto não considera que os primeiros 20 canais sejam a lista completa. O número efetivamente publicado na M3U depende ainda do teste de stream: canais sem stream HLS funcional são descartados.
