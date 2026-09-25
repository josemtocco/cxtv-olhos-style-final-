# CXTV Brasil — Lista M3U

Projeto no mesmo modelo do **Olhos na TV**: um único gerador Python na raiz do repositório, GitHub Actions para atualização automática e a playlist M3U publicada diretamente no próprio GitHub.

## Estrutura

```text
cxtvbrasil/
├── .github/
│   └── workflows/
│       └── atualizar.yml
├── gerar_m3u.py
├── requirements.txt
├── cxtvbrasil.m3u
├── README.md
└── .gitignore
```

## O que o gerador faz

- consulta a página de TVs do Brasil da CXTV;
- carrega a listagem dinâmica usando `Carregar Mais`;
- visita a página individual de cada canal;
- usa o nome exibido na página individual como `tvg-name`;
- identifica as categorias do canal;
- permite que o mesmo canal apareça em mais de uma categoria;
- captura URLs de reprodução solicitadas pelo player;
- rejeita URLs de páginas de YouTube, Facebook, Instagram, TikTok e da própria página do canal;
- testa os streams antes de incluí-los;
- para HLS, valida a playlist e pelo menos um segmento real;
- remove duplicidades;
- gera somente entradas com stream validado;
- grava `cxtvbrasil.m3u` na raiz do repositório.

## Formato M3U

Cada entrada usa:

- `tvg-id`
- `tvg-name`
- `tvg-country="BR"`
- `tvg-language="Português"`
- `group-title`

## Atualização automática

O GitHub Actions executa o gerador **4 vezes por dia** e também permite execução manual em:

**Actions → Atualizar lista CXTV Brasil → Run workflow**

Também há execução automática quando o `gerar_m3u.py`, `requirements.txt` ou o workflow é alterado.

## Playlist para SS IPTV

Depois da primeira execução, o arquivo fica disponível pela URL Raw do seu repositório, no formato:

```text
https://raw.githubusercontent.com/SEU-USUARIO/SEU-REPOSITORIO/main/cxtvbrasil.m3u
```

Substitua `SEU-USUARIO` e `SEU-REPOSITORIO` pelos dados do seu GitHub.

## Importante

Se nenhum stream válido for encontrado, o gerador encerra com erro e não cria uma nova playlist vazia. Assim, a última lista válida permanece no repositório.

A pasta `__pycache__` não deve ser enviada ao GitHub e já está incluída no `.gitignore`.


## Canais regionais

A descoberta agora consulta a página geral do Brasil **e as páginas individuais dos 26 estados + Distrito Federal**. Isso é importante porque a CXTV mantém páginas estaduais com canais regionais que podem não aparecer no primeiro conjunto carregado da página Brasil. A lista final é unificada e deduplicada antes dos testes de stream.

A CXTV disponibiliza uma página de estados com a quantidade de canais por estado e páginas específicas, por exemplo Rio Grande do Sul e São Paulo. O gerador consulta essas páginas automaticamente.
