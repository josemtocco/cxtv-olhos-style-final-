# CXTV Brasil — Regionais V7

Gerador M3U para o CXTV no mesmo conceito do projeto Olhos na TV.

## O que esta versão corrige

A versão anterior conseguia acessar a listagem nacional, mas as páginas estaduais retornavam HTTP 403 no GitHub Actions. Por isso `descobertos.json` mostrava `20` canais no Brasil e `0` nos estados.

A V7 muda a descoberta das páginas estaduais:

- tenta HTTP direto;
- usa Jina Reader quando o CXTV responde 403;
- para cada estado, quando há no máximo 20 canais, usa a API POST da Jina com JavaScript para clicar repetidamente em **Carregar Mais**;
- só depois usa o navegador Playwright como último fallback;
- mantém a correção do validador HLS da V6;
- gera `descobertos.json` com a quantidade descoberta por estado;
- não substitui silenciosamente a M3U por uma lista vazia.

A CXTV atualmente exibe contagens estaduais bem maiores que 20, por exemplo RS 54, SC 39, PB 24 e SP 212; as páginas públicas também mostram o botão `Carregar Mais`. Portanto, uma descoberta limitada aos 20 primeiros não atende ao objetivo de incluir os canais regionais. 

## Arquivos

- `gerar_m3u.py` — gerador, descoberta, captura e teste dos streams.
- `requirements.txt` — dependências Python.
- `.github/workflows/atualizar.yml` — execução automática a cada 6 horas.
- `cxtvbrasil.m3u` — playlist gerada.
- `status.json` — resumo da execução.
- `descobertos.json` — diagnóstico dos canais descobertos por página.

## GitHub Actions

O workflow executa automaticamente nos horários configurados e também pode ser iniciado manualmente em **Actions → Atualizar CXTV Brasil → Run workflow**.

A playlist final contém apenas streams que passaram pela validação HLS configurada no gerador.

## Observação

A descoberta depende da disponibilidade do CXTV para o serviço externo usado como fallback. Se o CXTV alterar o mecanismo do botão `Carregar Mais`, o arquivo `descobertos.json` mostrará a quantidade encontrada em cada estado para facilitar a manutenção.
