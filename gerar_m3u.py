import asyncio, hashlib, json, re, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE = 'https://www.cxtv.com.br'
BRASIL_URL = f'{BASE}/tv/paises/tvs-brasil'
ESTADOS_URL = f'{BASE}/tv/estados'
ESTADOS = ['ac','al','ap','am','ba','ce','df','es','go','ma','mt','ms','mg','pa','pb','pr','pe','pi','rj','rn','rs','ro','sc','sp','se','to']
OUT = Path('cxtvbrasil.m3u')
STATUS = Path('status.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36'


def clean(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def canonical(u):
    if not u:
        return ''
    p = urlparse(u)
    if p.scheme not in ('http', 'https'):
        return ''
    return f'{p.scheme}://{p.netloc}{p.path}'.rstrip('/')


def exact_name(html):
    soup = BeautifulSoup(html, 'html.parser')
    for sel in ('h1', '.tv-title', '.channel-title'):
        el = soup.select_one(sel)
        if el:
            n = clean(el.get_text(' ', strip=True))
            n = re.sub(r'\s+(?:Ao Vivo|Online)$', '', n, flags=re.I)
            if n:
                return n
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get('content'):
        return re.sub(r'\s+(?:Ao Vivo|Online)$', '', clean(og['content']), flags=re.I)
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    return re.sub(r'\s+(?:Ao Vivo|Online).*$','', clean(title), flags=re.I) or 'Canal sem nome'


def categories(html):
    soup = BeautifulSoup(html, 'html.parser')
    # The individual page usually exposes categories as short links/text near the title.
    bad = {'Brasil','Site','Acessar','Compartilhar','Adicionar aos Favoritos','Ativar som','Não está funcionando?'}
    found = []
    text = soup.get_text(' ', strip=True)
    known = ['Agronegócio','Alta Definição','Carros','Católica','Culinária','Cultura','Desenhos','Documentários','Educativos','Esportes','Étnicos','Evangélica','Filmes','Futebol','Moda','Música','Notícias','Novelas','Publicos','Seriados','Televendas','Tempo','Variedades']
    for c in known:
        if re.search(r'(?<!\w)'+re.escape(c)+r'(?!\w)', text, re.I):
            found.append(c)
    # Keep only categories appearing before the long description when possible; known list avoids most false positives.
    return found or ['Variedades']


def is_candidate_stream(u):
    if not u or not u.startswith(('http://','https://')):
        return False
    low = u.lower()
    blocked = ('youtube.com/watch','youtu.be/','facebook.com/','instagram.com/','tiktok.com/','cxtv.com.br/tv-ao-vivo/')
    return not any(x in low for x in blocked)

async def discover_page(page, page_url):
    """Descobre todos os canais de uma página CXTV, incluindo 'Carregar Mais'."""
    try:
        await page.goto(page_url, wait_until='domcontentloaded', timeout=90000)
        await page.wait_for_timeout(2000)
    except Exception:
        return []

    stable = 0
    for _ in range(120):
        links = await page.locator('a[href*="/tv-ao-vivo/"]').count()
        buttons = page.get_by_text('Carregar Mais', exact=True)
        if not await buttons.count():
            break
        try:
            await buttons.last.scroll_into_view_if_needed(timeout=2000)
            await buttons.last.click(timeout=5000)
            await page.wait_for_timeout(1200)
            new_links = await page.locator('a[href*="/tv-ao-vivo/"]').count()
            if new_links <= links:
                stable += 1
            else:
                stable = 0
            if stable >= 3:
                break
        except Exception:
            break

    hrefs = await page.locator('a[href*="/tv-ao-vivo/"]').evaluate_all('(els)=>els.map(e=>e.href)')
    return [canonical(h) for h in hrefs if '/tv-ao-vivo/' in canonical(h)]

async def discover(page):
    """Une Brasil + todos os estados. Assim canais regionais não ficam de fora."""
    urls = []
    pages = [BRASIL_URL] + [f'{BASE}/tv/estados/{uf}' for uf in ESTADOS]
    for page_url in pages:
        found = await discover_page(page, page_url)
        print(f'Descobertos {len(found)} canais em {page_url}')
        urls.extend(found)

    # Algumas páginas estaduais podem ter canais que também aparecem na página Brasil.
    seen = set()
    unique = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            unique.append(u)
    return unique

async def inspect(browser, url, sem):
    async with sem:
        context = await browser.new_context(user_agent=UA, locale='pt-BR', extra_http_headers={'Accept-Language':'pt-BR,pt;q=0.9'})
        page = await context.new_page()
        streams=[]
        async def response_handler(resp):
            u=resp.url
            ct=(resp.headers.get('content-type') or '').lower()
            if is_candidate_stream(u) and ('.m3u8' in u.lower() or 'mpegurl' in ct or 'x-mpegurl' in ct):
                streams.append(u)
        page.on('response', response_handler)
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(4500)
            html=await page.content()
            name=exact_name(html)
            cats=categories(html)
            # Give player time to request its playlist.
            await page.wait_for_timeout(4500)
            # Also inspect common embedded URLs in source.
            for m in re.findall(r'https?://[^\"\'<> ]+', html):
                if '.m3u8' in m.lower() and is_candidate_stream(m): streams.append(m)
            uniq=[]
            for s in streams:
                s=s.replace('&amp;','&')
                if s not in uniq: uniq.append(s)
            return {'url':url,'name':name,'categories':cats,'streams':uniq}
        except Exception as e:
            return {'url':url,'name':url.rstrip('/').split('/')[-1], 'categories':['Variedades'], 'streams':[], 'error':str(e)}
        finally:
            await context.close()

async def fetch_text(session, url, referer=None):
    headers={'User-Agent':UA,'Accept':'*/*'}
    if referer: headers['Referer']=referer
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15), allow_redirects=True) as r:
            if r.status not in (200,206): return None, r.status, str(r.url), r.headers
            data=await r.content.read(1024*1024)
            return data, r.status, str(r.url), r.headers
    except Exception:
        return None, 0, url, {}

async def valid_stream(session, url, referer=None, depth=0, seen=None):
    if seen is None: seen=set()
    if not url or url in seen or depth>2: return False
    seen.add(url)
    data,status,final,headers=await fetch_text(session,url,referer)
    if status not in (200,206) or not data: return False
    text=data.decode('utf-8','ignore')
    low=(headers.get('content-type','') or '').lower()
    if '#EXTM3U' in text or '.m3u8' in final.lower() or 'mpegurl' in low:
        if '#EXTM3U' not in text: return False
        # Master playlist: validate a media child.
        variants=[]
        lines=text.splitlines()
        for i,line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF') and i+1<len(lines):
                v=lines[i+1].strip()
                if v and not v.startswith('#'): variants.append(urljoin(final,v))
        if variants:
            for v in variants[:3]:
                if await valid_stream(session,v,referer,depth+1,seen): return True
            return False
        # Media playlist: require segments and verify one or two actual media objects.
        segs=[]
        for line in lines:
            line=line.strip()
            if line and not line.startswith('#'):
                segs.append(urljoin(final,line))
        if not segs: return False
        good=0
        for seg in segs[:2]:
            d,st,_,_=await fetch_text(session,seg,referer)
            if st in (200,206) and d and len(d)>256: good+=1
        return good>=1
    # Non-HLS: reject HTML and require enough bytes.
    if 'text/html' in low or data[:30].lower().startswith((b'<!doctype',b'<html')): return False
    return len(data)>4096

async def validate_and_write(items):
    connector=aiohttp.TCPConnector(limit=30, ssl=False)
    timeout=aiohttp.ClientTimeout(total=20)
    valid=[]
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        sem=asyncio.Semaphore(20)
        async def one(item):
            async with sem:
                for s in item['streams'][:5]:
                    if await valid_stream(session,s,item['url']):
                        return {**item,'stream':s}
            return None
        results=await asyncio.gather(*(one(i) for i in items))
        valid=[x for x in results if x]
    # de-duplicate by stream URL, retaining category information per channel/category.
    seen=set(); rows=[]
    for x in valid:
        for cat in x['categories']:
            key=(x['name'].casefold(),x['stream'],cat)
            if key in seen: continue
            seen.add(key)
            rows.append((x['name'],cat,x['stream'],x['url']))
    rows.sort(key=lambda r:(r[1].casefold(),r[0].casefold()))
    return rows


def write_m3u(rows):
    lines=['#EXTM3U']
    for name,cat,stream,_ in rows:
        tid=hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]
        safe_name=name.replace('"','')
        safe_cat=cat.replace('"','')
        lines.append(f'#EXTINF:-1 tvg-id="{tid}" tvg-name="{safe_name}" tvg-country="BR" tvg-language="Português" group-title="{safe_cat}",{safe_name}')
        lines.append(stream)
    OUT.write_text('\n'.join(lines)+'\n',encoding='utf-8')

async def main():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page=await browser.new_page(user_agent=UA, locale='pt-BR')
        urls=await discover(page)
        await page.close()
        print(f'Encontrados {len(urls)} canais na CXTV.')
        sem=asyncio.Semaphore(8)
        items=[]
        # Process in batches to avoid exhausting GitHub runner memory.
        for start in range(0,len(urls),80):
            batch=urls[start:start+80]
            res=await asyncio.gather(*(inspect(browser,u,sem) for u in batch))
            items.extend(res)
            print(f'Inspecionados {min(start+80,len(urls))}/{len(urls)}')
        await browser.close()
    rows=await validate_and_write(items)
    if not rows:
        print('ERRO: nenhum stream ativo validado. A playlist existente não será substituída.', file=sys.stderr)
        raise SystemExit(2)
    write_m3u(rows)
    STATUS.write_text(json.dumps({'fonte':BRASIL_URL,'canais_descobertos':len(urls),'canais_com_stream':len(set(r[0] for r in rows)),'entradas_m3u':len(rows)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Gerado {OUT} com {len(rows)} entradas.')

if __name__=='__main__':
    asyncio.run(main())
