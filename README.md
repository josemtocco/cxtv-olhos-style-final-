# CXTV Brasil — Regionais V8

Gerador de M3U para SS IPTV baseado na CXTV Brasil.

## O que esta versão corrige

- `descobertos.json` é gravado **durante a descoberta**, e não somente no final.
- Mesmo que a geração da M3U falhe, o GitHub Actions faz commit do diagnóstico.
- O workflow publica também o diagnóstico como artefato.
- A descoberta tenta HTTP, Jina Reader, Jina com JavaScript e Playwright.
- As páginas estaduais são tratadas como páginas com `Carregar Mais`.
- O diagnóstico informa `descobertos` e `esperados_no_site` por estado.
- A M3U só é substituída quando existe pelo menos um canal ativo validado.
- Atualização automática a cada 6 horas.

## Atenção sobre os regionais

A CXTV atualmente informa, na página de estados, quantidades diferentes por estado (por exemplo RS 54 e SP 212). A V8 não considera que encontrou os regionais apenas porque recebeu os primeiros 20 canais. O `descobertos.json` mostra a quantidade efetivamente descoberta e a quantidade esperada no catálogo naquele momento.

## Arquivos

- `gerar_m3u.py`
- `requirements.txt`
- `.github/workflows/atualizar.yml`
- `cxtvbrasil.m3u` — gerado pelo workflow
- `status.json` — gerado pelo workflow
- `descobertos.json` — diagnóstico da descoberta

## GitHub Actions

Execute manualmente em **Actions → Atualizar lista CXTV Brasil → Run workflow**.

Se o acesso à CXTV retornar 403 no runner, o workflow ainda salvará o `descobertos.json`, mesmo com a geração da M3U falhando. Isso permite identificar exatamente em qual etapa os canais regionais deixaram de ser descobertos.
