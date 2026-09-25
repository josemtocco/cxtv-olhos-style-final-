import asyncio, hashlib, json, re, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE='https://www.cxtv.com.br'
BRASIL_URL=f'{BASE}/tv/paises/tvs-brasil'
ESTADOS_URL=f'{BASE}/tv/estados'
OUT=Path('cxtvbrasil.m3u'); STATUS=Path('status.json'); DISC=Path('descobertos.json')
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36'

def clean(s): return re.sub(r'\s+',' ',s or '').strip()
def canonical(u):
    if not u: return ''
    p=urlparse(u)
    if p.scheme not in ('http','https'): return ''
    return f'{p.scheme}://{p.netloc}{p.path}'.rstrip('/')
def exact_name(html):
    soup=BeautifulSoup(html,'html.parser')
    for sel in ('h1','.tv-title','.channel-title'):
        el=soup.select_one(sel)
        if el:
            n=re.sub(r'\s+(?:Ao Vivo|Online)$','',clean(el.get_text(' ',strip=True)),flags=re.I)
            if n:return n
    for sel in ('meta[property="og:title"]','meta[name="twitter:title"]'):
        el=soup.select_one(sel)
        if el and el.get('content'):
            n=re.sub(r'\s+(?:Ao Vivo|Online)$','',clean(el['content']),flags=re.I)
            if n:return n
    return re.sub(r'\s+(?:Ao Vivo|Online).*$','',clean(soup.title.get_text(' ',strip=True) if soup.title else ''),flags=re.I) or 'Canal sem nome'
KNOWN=['Agronegócio','Alta Definição','Carros','Católica','Culinária','Cultura','Desenhos','Documentários','Educativos','Esportes','Étnicos','Evangélica','Filmes','Futebol','Moda','Música','Notícias','Novelas','Publicos','Seriados','Televendas','Tempo','Variedades']
def categories(html):
    text=BeautifulSoup(html,'html.parser').get_text(' ',strip=True)
    return [c for c in KNOWN if re.search(r'(?<!\w)'+re.escape(c)+r'(?!\w)',text,re.I)] or ['Variedades']
def is_candidate(u):
    if not u or not u.startswith(('http://','https://')): return False
    x=u.lower()
    return not any(a in x for a in ('youtube.com/watch','youtu.be/','facebook.com/','instagram.com/','tiktok.com/','cxtv.com.br/tv-ao-vivo/'))

def extract_channel_urls(html):
    soup=BeautifulSoup(html,'html.parser')
    found=set()
    # href, data-* e onclick: a CXTV pode colocar os links em diferentes atributos.
    for tag in soup.find_all(True):
        vals=[]
        for attr in ('href','data-href','data-url','data-link','data-channel','onclick'):
            v=tag.get(attr)
            if v: vals.append(str(v))
        for v in vals:
            for m in re.findall(r'(?:https?://(?:www\.)?cxtv\.com\.br)?(/tv-ao-vivo/[A-Za-z0-9_-]+)',v,re.I):
                found.add(canonical(urljoin(BASE,m)))
    # Fallback direto no HTML/JS renderizado.
    for m in re.findall(r'(?:https?://(?:www\.)?cxtv\.com\.br)?(/tv-ao-vivo/[A-Za-z0-9_-]+)',html,re.I):
        found.add(canonical(urljoin(BASE,m)))
    return sorted(u for u in found if '/tv-ao-vivo/' in u)

def count_channel_refs(html):
    return len(extract_channel_urls(html))

async def click_more(page):
    stable=0
    last=0
    for _ in range(180):
        html=await page.content(); current=count_channel_refs(html)
        if current>last: last=current; stable=0
        else: stable+=1
        loc=page.get_by_text('Carregar Mais',exact=True)
        if not await loc.count():
            # algumas versões do site usam botão/link com texto contendo espaços
            loc=page.locator('button, a').filter(has_text=re.compile(r'Carregar Mais',re.I))
        if not await loc.count(): break
        try:
            await loc.last.scroll_into_view_if_needed(timeout=3000)
            await loc.last.click(timeout=7000)
            await page.wait_for_timeout(1600)
            new=count_channel_refs(await page.content())
            if new<=current: stable+=1
            else: stable=0; last=new
            if stable>=5: break
        except Exception:
            break

async def discover_page(page,url):
    try:
        await page.goto(url,wait_until='domcontentloaded',timeout=90000)
        await page.wait_for_timeout(2200)
        await click_more(page)
        html=await page.content()
        hrefs=extract_channel_urls(html)
        # Última tentativa usando o DOM, caso o HTML tenha sido alterado por JS.
        try:
            dom=await page.locator('a').evaluate_all('els=>els.map(e=>[e.href,e.getAttribute("data-href"),e.getAttribute("data-url"),e.getAttribute("onclick")]).flat().filter(Boolean)')
            for h in dom:
                hrefs.append(canonical(urljoin(BASE,str(h)))) if '/tv-ao-vivo/' in str(h) else None
        except Exception: pass
        return sorted(set(h for h in hrefs if '/tv-ao-vivo/' in h))
    except Exception as e:
        print('Falha descoberta',url,e); return []

async def discover(page):
    state_urls=[]
    try:
        await page.goto(ESTADOS_URL,wait_until='domcontentloaded',timeout=90000)
        await page.wait_for_timeout(1800)
        html=await page.content()
        soup=BeautifulSoup(html,'html.parser')
        for tag in soup.find_all(True):
            for attr in ('href','data-href','data-url'):
                v=tag.get(attr)
                if v:
                    h=canonical(urljoin(BASE,str(v)))
                    if re.fullmatch(r'https://www\.cxtv\.com\.br/tv/estados/[a-z]{2}',h,re.I): state_urls.append(h.lower())
        for h in re.findall(r'(?:https?://(?:www\.)?cxtv\.com\.br)?(/tv/estados/[a-z]{2})',html,re.I):
            state_urls.append(canonical(urljoin(BASE,h)).lower())
    except Exception as e: print('Falha na página de estados:',e)
    if not state_urls:
        state_urls=[f'{BASE}/tv/estados/{uf}' for uf in 'ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro sc sp se to'.split()]
    state_urls=sorted(set(state_urls))
    pages=[BRASIL_URL]+state_urls
    allurls=[]; counts={}
    for u in pages:
        found=await discover_page(page,u); counts[u]=len(found); allurls.extend(found); print(f'Descobertos {len(found)} em {u}',flush=True)
    seen=set(); unique=[]
    for u in allurls:
        if u and u not in seen: seen.add(u); unique.append(u)
    DISC.write_text(json.dumps({'paginas':counts,'canais_unicos':len(unique),'canais':unique},ensure_ascii=False,indent=2),encoding='utf-8')
    return unique

async def inspect(browser,url,sem):
    async with sem:
        ctx=await browser.new_context(user_agent=UA,locale='pt-BR',extra_http_headers={'Accept-Language':'pt-BR,pt;q=0.9'})
        page=await ctx.new_page(); streams=[]
        def add(u):
            u=u.replace('&amp;','&')
            if is_candidate(u) and u not in streams: streams.append(u)
        async def resp(r):
            u=r.url; ct=(r.headers.get('content-type') or '').lower()
            if is_candidate(u) and ('.m3u8' in u.lower() or 'mpegurl' in ct or 'x-mpegurl' in ct): add(u)
        page.on('response',resp)
        try:
            await page.goto(url,wait_until='domcontentloaded',timeout=60000); await page.wait_for_timeout(2500)
            html=await page.content(); name=exact_name(html); cats=categories(html)
            # Tenta ativar players que não iniciam automaticamente.
            for txt in ['Ativar som','Play','PLAY','Assistir','Iniciar']:
                try:
                    loc=page.get_by_text(txt,exact=True)
                    if await loc.count(): await loc.first.click(timeout=1800); await page.wait_for_timeout(1800)
                except Exception: pass
            for sel in ['button[aria-label*="play" i]','video','[class*="play" i]']:
                try:
                    loc=page.locator(sel)
                    if await loc.count(): await loc.first.click(timeout=1200,force=True); await page.wait_for_timeout(1000)
                except Exception: pass
            # Aguarda mais tráfego após interação.
            await page.wait_for_timeout(3500)
            # Visita iframes de player encontrados no canal; isso recupera streams que não carregam no frame principal.
            frames=await page.locator('iframe').evaluate_all('(els)=>els.map(e=>e.src).filter(Boolean)')
            for frame_url in list(dict.fromkeys(frames))[:4]:
                if not frame_url.startswith(('http://','https://')): continue
                try:
                    p2=await ctx.new_page(); p2.on('response',resp)
                    await p2.goto(frame_url,wait_until='domcontentloaded',timeout=25000); await p2.wait_for_timeout(3500)
                    for txt in ['Ativar som','Play','PLAY','Assistir','Iniciar']:
                        try:
                            loc=p2.get_by_text(txt,exact=True)
                            if await loc.count(): await loc.first.click(timeout=1000); await p2.wait_for_timeout(1200)
                        except Exception: pass
                    await p2.wait_for_timeout(1500); await p2.close()
                except Exception: pass
            # URLs explícitas no HTML.
            for m in re.findall(r'https?://[^"\'<> ]+',html):
                if '.m3u8' in m.lower(): add(m)
            return {'url':url,'name':name,'categories':cats,'streams':streams}
        except Exception as e:
            return {'url':url,'name':url.rstrip('/').split('/')[-1],'categories':['Variedades'],'streams':[],'error':str(e)}
        finally: await ctx.close()

async def fetch(session,u,ref=None):
    h={'User-Agent':UA,'Accept':'*/*'}
    if ref:h['Referer']=ref
    try:
        async with session.get(u,headers=h,timeout=aiohttp.ClientTimeout(total=18),allow_redirects=True) as r:
            d=await r.content.read(1024*1024); return d,r.status,str(r.url),r.headers
    except Exception:return b'',0,u,{}
async def valid(session,u,ref=None,depth=0,seen=None):
    seen=seen or set()
    if not u or u in seen or depth>2:return False
    seen.add(u); d,st,final,h=await fetch(session,u,ref)
    if st not in (200,206) or not d:return False
    t=d.decode('utf-8','ignore'); ct=(h.get('content-type') or '').lower()
    if '#EXTM3U' in t or '.m3u8' in final.lower() or 'mpegurl' in ct:
        if '#EXTM3U' not in t:return False
        lines=t.splitlines(); variants=[]; segs=[]
        for i,l in enumerate(lines):
            l=l.strip()
            if l.startswith('#EXT-X-STREAM-INF') and i+1<len(lines):
                v=lines[i+1].strip()
                if v and not v.startswith('#'):variants.append(urljoin(final,v))
            elif l and not l.startswith('#'):segs.append(urljoin(final,l))
        if variants:return any(await valid(session,v,ref,depth+1,seen) for v in variants[:3])
        if not segs:return False
        for s in segs[:3]:
            sd,ss,_,_=await fetch(session,s,ref)
            if ss in (200,206) and len(sd)>256:return True
        return False
    if 'text/html' in ct or d[:30].lower().startswith((b'<!doctype',b'<html')):return False
    return len(d)>4096

async def validate(items):
    conn=aiohttp.TCPConnector(limit=25,ssl=False)
    validitems=[]
    async with aiohttp.ClientSession(connector=conn) as s:
        sem=asyncio.Semaphore(15)
        async def one(x):
            async with sem:
                for st in x['streams'][:8]:
                    if await valid(s,st,x['url']): return {**x,'stream':st}
            return None
        out=await asyncio.gather(*(one(x) for x in items)); validitems=[x for x in out if x]
    seen=set(); rows=[]
    for x in validitems:
        for c in x['categories']:
            k=(x['name'].casefold(),x['stream'],c.casefold())
            if k not in seen:seen.add(k);rows.append((x['name'],c,x['stream']))
    rows.sort(key=lambda r:(r[1].casefold(),r[0].casefold()));return rows

def write(rows):
    a=['#EXTM3U']
    for n,c,u in rows:
        n=n.replace('"','');c=c.replace('"','');tid=hashlib.sha1(n.encode()).hexdigest()[:12]
        a += [f'#EXTINF:-1 tvg-id="{tid}" tvg-name="{n}" tvg-country="BR" tvg-language="Português" group-title="{c}",{n}',u]
    OUT.write_text('\n'.join(a)+'\n',encoding='utf-8')

async def main():
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        p=await b.new_page(user_agent=UA,locale='pt-BR'); urls=await discover(p); await p.close()
        print(f'Total descoberto: {len(urls)}')
        sem=asyncio.Semaphore(6); items=[]
        for start in range(0,len(urls),50):
            res=await asyncio.gather(*(inspect(b,u,sem) for u in urls[start:start+50]));items.extend(res)
            print(f'Inspecionados {min(start+50,len(urls))}/{len(urls)}')
        await b.close()
    rows=await validate(items)
    if not rows: raise SystemExit('Nenhum canal ativo validado; lista existente preservada.')
    write(rows)
    STATUS.write_text(json.dumps({'canais_descobertos':len(urls),'canais_com_stream':len(set(r[0] for r in rows)),'entradas_m3u':len(rows),'regionais_incluidos':True},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Gerado {OUT} com {len(rows)} entradas.')

if __name__=='__main__':asyncio.run(main())
