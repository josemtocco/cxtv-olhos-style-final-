# CXTV Brasil — modelo Olhos na TV

Gerador automático de M3U para os canais de TV do Brasil cadastrados na CXTV, incluindo as páginas estaduais.

## O que esta versão corrige

- Descoberta por HTTP antes do Chromium, evitando depender do modo headless para localizar os cards.
- Fallback para Playwright e botão **Carregar Mais**.
- Consulta a página Brasil e as 27 UFs.
- Deduplicação das páginas de canais.
- Nome obtido da página individual.
- Categorias preservadas.
- Captura de streams HLS do player e de iframes.
- Validação de playlist HLS e de segmentos reais.
- Somente streams validados entram em `cxtvbrasil.m3u`.
- `descobertos.json` registra quantos canais foram encontrados por página.
- Em falhas, o workflow salva um artefato `diagnostico-cxtv` com `descobertos.json` e, quando disponível, `cxtv_debug.html`.
- Atualização automática a cada 6 horas e execução manual.

## Arquivos

- `gerar_m3u.py`
- `requirements.txt`
- `.github/workflows/atualizar.yml`
- `cxtvbrasil.m3u`
- `status.json`
- `descobertos.json`

A CXTV mantém páginas estaduais separadas; por exemplo, a página do Rio Grande do Sul lista 54 canais atualmente. O gerador consulta essas páginas além da listagem Brasil.


## V6 — correções importantes

- Corrige o erro `TypeError: 'async_generator' object is not iterable` na validação HLS.
- Corrige o compartilhamento do conjunto `seen` durante a validação recursiva de variantes HLS.
- Quando a CXTV responde `403` ao GitHub Actions, tenta primeiro a descoberta pelo Jina Reader e só depois pelo Chromium.
- O diagnóstico registra a fonte usada (`http`, `jina` ou `browser`) em `descobertos.json`.
- O job tem limite de 30 minutos para acomodar a consulta das páginas estaduais e a validação dos streams.

A CXTV continua mantendo páginas estaduais separadas; a página de estados atualmente informa 54 canais no RS, 212 em SP, 63 em MG e 44 no PR.
