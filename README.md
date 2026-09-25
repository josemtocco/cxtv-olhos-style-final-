# CXTV Brasil — todos os canais e regionais (V4)

Projeto no mesmo modelo do Olhos na TV para gerar `cxtvbrasil.m3u` automaticamente a partir da CXTV.

## Correção principal da V4

A versão anterior encontrava os links `/tv-ao-vivo/...`, mas depois os descartava por engano no filtro de candidatos. Isso fazia o log mostrar `Descobertos 0` para Brasil e para todos os estados.

A V4 corrige esse filtro e também usa diretamente `a[href*="/tv-ao-vivo/"]` no DOM.

## Fontes consultadas

- Página Brasil: https://www.cxtv.com.br/tv/paises/tvs-brasil
- Página de estados: https://www.cxtv.com.br/tv/estados
- Todas as UFs brasileiras, com fallback fixo caso a página de estados não carregue.

## Saídas

- `cxtvbrasil.m3u`
- `status.json`
- `descobertos.json`

Somente streams que passam pela validação entram na M3U. Se nenhum canal ativo for validado, o workflow falha e preserva a lista anterior.
