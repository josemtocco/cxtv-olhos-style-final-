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
EXPECTED={'ac':2,'al':11,'ap':1,'am':10,'ba':34,'ce':32,'df':22,'es':17,'go':20,'ma':17,'mt':21,'ms':14,'mg':63,'pa':21,'pb':24,'pr':44,'pe':17,'pi':15,'rj':58,'rn':22,'rs':54,'ro':11,'sc':39,'sp':212,'se':5,'to':2}
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36'
JINA='https://r.jina.ai/'

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
    return not any(a in x for a in ('youtube.com/watch','youtu.be/','facebook.com/','instagram.com/','tiktok.com/',))

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

async def fetch_page(session, url):
    headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'pt-BR,pt;q=0.9'}
    try:
        async with session.get(url,headers=headers,timeout=aiohttp.ClientTimeout(total=30),allow_redirects=True) as r:
            body=await r.text(errors='ignore')
            return r.status, body, str(r.url)
    except Exception as e:
        print(f'HTTP falhou {url}: {e}', flush=True)
        return 0,'',url

async def fetch_jina(session, url, expand=False):
    """Busca a listagem pela Jina.

    V7 usa dois modos: GET normal e, para páginas estaduais, POST com JavaScript
    que clica repetidamente em "Carregar Mais" antes da extração. Isso é
    importante porque a CXTV mostra apenas a primeira página de canais no HTML
    inicial e carrega os demais dinamicamente.
    """
    reader=JINA+url
    headers={
        'User-Agent':UA,
        'Accept':'application/json',
        'X-Engine':'browser',
        'X-Timeout':'60',
        'X-Locale':'pt-BR',
        'X-With-Links-Summary':'all',
        'X-Retain-Links':'all',
        'X-No-Cache':'true',
    }
    try:
        if expand:
            js="""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              for (let i = 0; i < 120; i++) {
                const buttons = [...document.querySelectorAll('button, a, input, [role="button"]')];
                const b = buttons.find(el => (el.innerText || el.value || '').trim().toLowerCase().includes('carregar mais'));
                if (!b) break;
                b.scrollIntoView({block:'center'});
                b.click();
                await sleep(1600);
              }
              await sleep(2000);
            }
            """
            payload={'url':url,'js':js}
            async with session.post(reader,headers=headers,json=payload,timeout=aiohttp.ClientTimeout(total=90)) as r:
                raw=await r.text(errors='ignore')
        else:
            async with session.get(reader,headers=headers,timeout=aiohttp.ClientTimeout(total=75)) as r:
                raw=await r.text(errors='ignore')
        if r.status != 200:
            print(f'Jina falhou {url}: status={r.status} bytes={len(raw)} expand={expand}',flush=True)
            return 0,''
        try:
            obj=json.loads(raw)
            body=obj.get('content','') if isinstance(obj,dict) else raw
        except Exception:
            body=raw
        return 200, body
    except Exception as e:
        print(f'Jina falhou {url}: {e} expand={expand}',flush=True)
        return 0,''

async def click_more(page):
    last=0
    stable=0
    for _ in range(120):
        html=await page.content(); current=count_channel_refs(html)
        if current>last: last=current; stable=0
        else: stable+=1
        try:
            loc=page.locator('text=Carregar Mais')
            if not await loc.count():
                break
            await loc.last.scroll_into_view_if_needed(timeout=4000)
            await loc.last.click(timeout=8000)
            await page.wait_for_timeout(1800)
            new=count_channel_refs(await page.content())
            if new<=current: stable+=1
            else: stable=0; last=new
            if stable>=4: break
        except Exception:
            break

async def browser_discover(page,url):
    try:
        await page.goto(url,wait_until='domcontentloaded',timeout=90000)
        await page.wait_for_timeout(2500)
        await click_more(page)
        html=await page.content()
        found=extract_channel_urls(html)
        try:
            vals=await page.locator('a[href*="/tv-ao-vivo/"]').evaluate_all('(els)=>els.map(e=>e.href)')
            found += [canonical(x) for x in vals]
        except Exception: pass
        return sorted(set(x for x in found if '/tv-ao-vivo/' in x)), html
    except Exception as e:
        print(f'Browser falhou {url}: {e}',flush=True)
        return [],''

def write_discovery(counts, debug, unique):
    estados={}
    for u,n in counts.items():
        m=re.search(r'/tv/estados/([a-z]{2})$',u,re.I)
        if m:
            uf=m.group(1).lower()
            estados[uf]={'descobertos':n,'esperados_no_site':EXPECTED.get(uf)}
    payload={'paginas':counts,'diagnostico':debug,'canais_unicos':len(unique),'canais':unique,'estados':estados,'observacao':'Arquivo gravado incrementalmente durante a descoberta; os numeros esperados sao os exibidos atualmente pela pagina de estados da CXTV.'}
    DISC.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')

async def discover(page):
    pages=[BRASIL_URL]+[f'{BASE}/tv/estados/{uf}' for uf in 'ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro sc sp se to'.split()]
    allurls=[]; counts={}; debug=[]
    timeout=aiohttp.ClientTimeout(total=45)
    last_jina=0.0
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for u in pages:
            is_state='/tv/estados/' in u
            status,html,final=await fetch_page(session,u)
            found=extract_channel_urls(html) if html else []
            source='http'
            if found:
                print(f'HTTP descobriu {len(found)} em {u}',flush=True)
            elif status == 403:
                now=asyncio.get_running_loop().time()
                wait=max(0.0,3.3-(now-last_jina))
                if wait: await asyncio.sleep(wait)
                jstatus,jhtml=await fetch_jina(session,u,expand=False)
                last_jina=asyncio.get_running_loop().time()
                found=extract_channel_urls(jhtml) if jhtml else []
                source='jina'
                print(f'Jina inicial descobriu {len(found)} em {u}',flush=True)
            else:
                print(f'HTTP descobriu 0 em {u} (status={status}, bytes={len(html)})',flush=True)

            # A listagem estadual é paginada por "Carregar Mais". Se o GET
            # trouxer somente a primeira leva (ou nada), peça à Jina para
            # executar JS e clicar no botão até que ele desapareça.
            if is_state and len(found) <= 20:
                now=asyncio.get_running_loop().time()
                wait=max(0.0,3.3-(now-last_jina))
                if wait: await asyncio.sleep(wait)
                jstatus,jhtml=await fetch_jina(session,u,expand=True)
                last_jina=asyncio.get_running_loop().time()
                expanded=extract_channel_urls(jhtml) if jhtml else []
                if len(expanded)>len(found):
                    found=expanded
                    source='jina-js'
                print(f'Jina JS descobriu {len(expanded)} em {u}',flush=True)

            # Browser remains a final fallback. Unlike V6, it is also used
            # when Jina returned a tiny/empty result, not only on HTTP 0.
            if not found:
                found,bh=await browser_discover(page,u)
                if bh and len(bh)>1000:
                    Path('cxtv_debug.html').write_text(bh,encoding='utf-8')
                source='browser'
                print(f'Browser descobriu {len(found)} em {u}',flush=True)

            counts[u]=len(found); allurls.extend(found)
            debug.append({'url':u,'status':status,'bytes':len(html),'fonte':source,'descobertos':len(found)})
            tmp_seen=set(); tmp_unique=[]
            for x in allurls:
                if x and x not in tmp_seen: tmp_seen.add(x); tmp_unique.append(x)
            write_discovery(counts, debug, tmp_unique)
            print(f'Diagnostico atualizado: {len(tmp_unique)} canais descobertos ate agora.',flush=True)
    seen=set(); unique=[]
    for u in allurls:
        if u and u not in seen: seen.add(u); unique.append(u)
    write_discovery(counts, debug, unique)
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
    if seen is None: seen=set()
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
        if variants:
            for v in variants[:3]:
                if await valid(session,v,ref,depth+1,seen):
                    return True
            return False
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
    STATUS.write_text(json.dumps({'canais_descobertos':len(urls),'canais_com_stream':len(set(r[0] for r in rows)),'entradas_m3u':len(rows),'regionais_incluidos':True,'validacao_hls_segmentos':True},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Gerado {OUT} com {len(rows)} entradas.')

if __name__=='__main__':asyncio.run(main())
