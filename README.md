# CXTV Brasil — modelo Olhos na TV

Gerador automático de M3U para SS IPTV.

## O que esta versão corrige
- Consulta a página Brasil da CXTV.
- Descobre automaticamente as páginas oficiais de todos os estados na página `tv/estados`.
- Varre todos os canais de cada estado, incluindo regionais.
- Usa a página individual para obter o nome correto.
- Tenta ativar players e visitar iframes para capturar streams.
- Valida playlist HLS e pelo menos um segmento real.
- Remove streams inválidos e duplicados.
- Gera `cxtvbrasil.m3u`, `status.json` e `descobertos.json`.

## GitHub Actions
Execute manualmente em **Actions → Atualizar lista CXTV Brasil → Run workflow**.
A atualização automática ocorre 4 vezes ao dia.

`descobertos.json` é mantido no repositório para permitir conferir quantos canais foram encontrados em cada página estadual.
