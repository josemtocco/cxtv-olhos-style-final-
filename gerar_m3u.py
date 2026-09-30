import asyncio, hashlib, json, re, time
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE='https://www.cxtv.com.br'
OUT=Path('cxtvbrasil.m3u')
STATUS=Path('status.json')
DISC=Path('descobertos.json')
SOURCES=Path('fontes_estados.json')
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
JINA='https://r.jina.ai/'
JINA_SEARCH='https://s.jina.ai/'
EXPECTED={'ac':2,'al':11,'ap':1,'am':10,'ba':34,'ce':32,'df':22,'es':17,'go':20,'ma':17,'mt':21,'ms':14,'mg':63,'pa':21,'pb':24,'pr':44,'pe':17,'pi':15,'rj':58,'rn':22,'rs':54,'ro':11,'sc':39,'sp':212,'se':5,'to':2}
STATE_NAMES={'rs':'Rio Grande do Sul','rj':'Rio de Janeiro','sp':'São Paulo','sc':'Santa Catarina','pr':'Paraná','mg':'Minas Gerais','ce':'Ceará','ba':'Bahia','pa':'Pará','pb':'Paraíba','rn':'Rio Grande do Norte','pi':'Piauí','df':'Distrito Federal','mt':'Mato Grosso','ms':'Mato Grosso do Sul','go':'Goiás','es':'Espírito Santo','am':'Amazonas','al':'Alagoas','ma':'Maranhão'}
SEARCH_TERMS=['Variedades','Notícias','Cultura','Esportes','Filmes','Desenhos','Seriados','Publicos','Música','Educativos','Futebol','Alta Definição']
KNOWN=['Agronegócio','Alta Definição','Carros','Católica','Culinária','Cultura','Desenhos','Documentários','Educativos','Esportes','Étnicos','Evangélica','Filmes','Futebol','Moda','Música','Notícias','Novelas','Publicos','Seriados','Televendas','Tempo','Variedades']

def clean(s): return re.sub(r'\s+',' ',s or '').strip()
def canonical(u):
    if not u:return ''
    p=urlparse(u)
    if p.scheme not in ('http','https'):return ''
    return f'{p.scheme}://{p.netloc}{p.path}'.rstrip('/')
def extract_channel_urls(html):
    if not html:return []
    soup=BeautifulSoup(html,'html.parser'); found=set()
    for tag in soup.find_all(True):
        for attr in ('href','data-href','data-url','data-link','data-channel','onclick'):
            v=tag.get(attr)
            if not v:continue
            for m in re.findall(r'(?:https?://(?:www\.)?cxtv\.com\.br)?(/tv-ao-vivo/[A-Za-z0-9_-]+)',str(v),re.I):
                found.add(canonical(urljoin(BASE,m)))
    for m in re.findall(r'(?:https?://(?:www\.)?cxtv\.com\.br)?(/tv-ao-vivo/[A-Za-z0-9_-]+)',html,re.I):
        found.add(canonical(urljoin(BASE,m)))
    return sorted(x for x in found if '/tv-ao-vivo/' in x)

def write_discovery(paginas, diagnostico, unique, buscas=None):
    estados={}
    for uf,url in ((k,v) for k,v in SOURCES_DATA['estados'].items()):
        estados[uf]={'descobertos':paginas.get(url,0),'esperados_no_site':EXPECTED.get(uf),'nome':STATE_NAMES.get(uf,uf.upper())}
    payload={'fontes_utilizadas':SOURCES_DATA,'paginas':paginas,'estados':estados,'diagnostico':diagnostico,'canais_unicos':len(unique),'canais':unique,'buscas':buscas or [],'atualizado_em':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    DISC.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')

async def fetch(session,url):
    try:
        h={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'pt-BR,pt;q=0.9'}
        async with session.get(url,headers=h,timeout=aiohttp.ClientTimeout(total=45),allow_redirects=True) as r:
            return r.status,await r.text(errors='ignore'),str(r.url)
    except Exception as e:
        return 0,'',url

async def jina_read(session,url,wait_selector=None):
    h={'User-Agent':UA,'Accept':'application/json','X-Engine':'browser','X-Timeout':'30','X-Locale':'pt-BR','X-Retain-Links':'all','X-With-Links-Summary':'all','X-No-Cache':'true'}
    if wait_selector:h['X-Wait-For-Selector']=wait_selector
    try:
        async with session.get(JINA+url,headers=h,timeout=aiohttp.ClientTimeout(total=55)) as r:
            raw=await r.text(errors='ignore')
            if r.status!=200:return 0,''
            try:
                obj=json.loads(raw); return 200,obj.get('content','') if isinstance(obj,dict) else raw
            except Exception:return 200,raw
    except Exception:return 0,''

async def jina_search(session,query,page=1):
    # Jina Search aceita a consulta no caminho e parâmetros de paginação.
    urls=[f'{JINA_SEARCH}{quote(query,safe="")}?num=20&page={page}', f'{JINA_SEARCH}?q={quote(query)}&num=20&page={page}']
    h={'User-Agent':UA,'Accept':'application/json','X-No-Cache':'true','X-Locale':'pt-BR'}
    for u in urls:
        try:
            async with session.get(u,headers=h,timeout=aiohttp.ClientTimeout(total=45)) as r:
                raw=await r.text(errors='ignore')
                if r.status!=200:continue
                try:
                    obj=json.loads(raw)
                    items=obj.get('data',obj) if isinstance(obj,dict) else obj
                    if isinstance(items,list):
                        text='\n'.join((x.get('url','')+' '+x.get('title','')+' '+x.get('description','')) if isinstance(x,dict) else str(x) for x in items)
                    else:text=raw
                except Exception:text=raw
                return 200,text
        except Exception:continue
    return 0,''

async def browser_discover(page,url):
    try:
        await page.goto(url,wait_until='domcontentloaded',timeout=90000)
        await page.wait_for_timeout(2500)
        last=0
        for _ in range(100):
            html=await page.content(); n=len(extract_channel_urls(html))
            try:
                b=page.get_by_text('Carregar Mais',exact=True)
                if not await b.count():break
                await b.last.scroll_into_view_if_needed(timeout=3000)
                await b.last.click(timeout=6000)
                await page.wait_for_timeout(1800)
                n2=len(extract_channel_urls(await page.content()))
                if n2<=n and n2<=last:break
                last=n2
            except Exception:break
        html=await page.content(); found=extract_channel_urls(html)
        try: found += [canonical(x) for x in await page.locator('a[href*="/tv-ao-vivo/"]').evaluate_all('(els)=>els.map(e=>e.href)')]
        except Exception:pass
        return sorted(set(found))
    except Exception:return []

async def discover(page):
    global SOURCES_DATA
    pages=[SOURCES_DATA['brasil']]+list(SOURCES_DATA['estados'].values())
    allurls=[]; paginas={}; diagnostico=[]; buscas=[]
    async with aiohttp.ClientSession() as session:
        for idx,url in enumerate(pages):
            status,html,final=await fetch(session,url)
            found=extract_channel_urls(html)
            source='http' if found else 'http-403'
            if not found:
                js,body=await jina_read(session,url,'a[href*="/tv-ao-vivo/"]')
                found=extract_channel_urls(body)
                if found:source='jina'
            # O mecanismo de busca serve para completar a pagina estadual quando
            # o site devolve somente os primeiros 20 canais.
            m=re.search(r'/tv/estados/([a-z]{2})$',url,re.I); uf=m.group(1).lower() if m else None
            target=EXPECTED.get(uf,20) if uf else 20
            if uf and len(found)<target:
                for term in SEARCH_TERMS:
                    q=f'site:cxtv.com.br/tv-ao-vivo "Brasil - {uf.upper()}" "{term}"'
                    ss,body=await jina_search(session,q,1)
                    extra=extract_channel_urls(body)
                    before=len(found); found=sorted(set(found+extra))
                    buscas.append({'uf':uf,'consulta':q,'pagina':1,'encontrados':len(extra),'total_estado':len(found)})
                    if len(found)>=target:break
                    await asyncio.sleep(3.2)
                    # segunda página da mesma consulta, somente quando necessário
                    if len(found)<target:
                        ss2,body2=await jina_search(session,q,2)
                        extra2=extract_channel_urls(body2); found=sorted(set(found+extra2))
                        buscas.append({'uf':uf,'consulta':q,'pagina':2,'encontrados':len(extra2),'total_estado':len(found)})
                    if len(found)>=target:break
                    if len(found)==before and term in ('Música','Educativos','Futebol'):continue
            if uf and len(found)<target:
                browser=await browser_discover(page,url)
                if len(browser)>len(found):found=browser;source='browser'
            paginas[url]=len(found); allurls.extend(found)
            diagnostico.append({'url':url,'status':status,'bytes':len(html),'fonte':source,'descobertos':len(found),'esperados_no_site':target})
            unique=sorted(set(allurls)); write_discovery(paginas,diagnostico,unique,buscas)
            print(f'{uf or "brasil"}: {len(found)} descobertos / esperado {target}',flush=True)
    return sorted(set(allurls))

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
    return 'Canal sem nome'

def categories(html):
    text=BeautifulSoup(html,'html.parser').get_text(' ',strip=True)
    return [c for c in KNOWN if re.search(r'(?<!\w)'+re.escape(c)+r'(?!\w)',text,re.I)] or ['Variedades']
def is_candidate(u):
    if not u or not u.startswith(('http://','https://')):return False
    return not any(x in u.lower() for x in ('youtube.com/watch','youtu.be/','facebook.com/','instagram.com/','tiktok.com/'))

async def inspect(browser,url,sem):
    async with sem:
        ctx=await browser.new_context(user_agent=UA,locale='pt-BR',extra_http_headers={'Accept-Language':'pt-BR,pt;q=0.9'})
        page=await ctx.new_page(); streams=[]
        def add(u):
            u=u.replace('&amp;','&')
            if is_candidate(u) and u not in streams:streams.append(u)
        async def resp(r):
            u=r.url; ct=(r.headers.get('content-type') or '').lower()
            if is_candidate(u) and ('.m3u8' in u.lower() or 'mpegurl' in ct):add(u)
        page.on('response',resp)
        try:
            await page.goto(url,wait_until='domcontentloaded',timeout=60000); await page.wait_for_timeout(2500)
            html=await page.content(); name=exact_name(html); cats=categories(html)
            for txt in ['Ativar som','Play','PLAY','Assistir','Iniciar']:
                try:
                    loc=page.get_by_text(txt,exact=True)
                    if await loc.count():await loc.first.click(timeout=1800);await page.wait_for_timeout(1600)
                except Exception:pass
            for sel in ['button[aria-label*="play" i]','video','[class*="play" i]']:
                try:
                    loc=page.locator(sel)
                    if await loc.count():await loc.first.click(timeout=1200,force=True);await page.wait_for_timeout(1000)
                except Exception:pass
            await page.wait_for_timeout(3000)
            frames=await page.locator('iframe').evaluate_all('(els)=>els.map(e=>e.src).filter(Boolean)')
            for fu in list(dict.fromkeys(frames))[:4]:
                try:
                    p2=await ctx.new_page();p2.on('response',resp);await p2.goto(fu,wait_until='domcontentloaded',timeout=25000);await p2.wait_for_timeout(3500);await p2.close()
                except Exception:pass
            for m in re.findall(r'https?://[^"\'<> ]+',html):
                if '.m3u8' in m.lower():add(m)
            return {'url':url,'name':name,'categories':cats,'streams':streams}
        except Exception as e:
            return {'url':url,'name':url.rstrip('/').split('/')[-1],'categories':['Variedades'],'streams':[],'error':str(e)}
        finally:await ctx.close()

async def fetch_bytes(session,u,ref=None):
    h={'User-Agent':UA,'Accept':'*/*'}
    if ref:h['Referer']=ref
    try:
        async with session.get(u,headers=h,timeout=aiohttp.ClientTimeout(total=18),allow_redirects=True) as r:
            return await r.content.read(1024*1024),r.status,str(r.url),r.headers
    except Exception:return b'',0,u,{}
async def valid(session,u,ref=None,depth=0,seen=None):
    if seen is None:seen=set()
    if not u or u in seen or depth>2:return False
    seen.add(u);d,st,final,h=await fetch_bytes(session,u,ref)
    if st not in (200,206) or not d:return False
    t=d.decode('utf-8','ignore');ct=(h.get('content-type') or '').lower()
    if '#EXTM3U' in t or '.m3u8' in final.lower() or 'mpegurl' in ct:
        if '#EXTM3U' not in t:return False
        lines=t.splitlines();variants=[];segs=[]
        for i,l in enumerate(lines):
            l=l.strip()
            if l.startswith('#EXT-X-STREAM-INF') and i+1<len(lines):
                v=lines[i+1].strip()
                if v and not v.startswith('#'):variants.append(urljoin(final,v))
            elif l and not l.startswith('#'):segs.append(urljoin(final,l))
        for v in variants[:3]:
            if await valid(session,v,ref,depth+1,seen):return True
        for s in segs[:3]:
            sd,ss,_,_=await fetch_bytes(session,s,ref)
            if ss in (200,206) and len(sd)>256:return True
        return False
    if 'text/html' in ct or d[:30].lower().startswith((b'<!doctype',b'<html')):return False
    return len(d)>4096

async def validate(items):
    conn=aiohttp.TCPConnector(limit=25,ssl=False);rows=[]
    async with aiohttp.ClientSession(connector=conn) as s:
        sem=asyncio.Semaphore(15)
        async def one(x):
            async with sem:
                for st in x['streams'][:8]:
                    if await valid(s,st,x['url']):return {**x,'stream':st}
            return None
        out=await asyncio.gather(*(one(x) for x in items));validitems=[x for x in out if x]
    seen=set()
    for x in validitems:
        for c in x['categories']:
            k=(x['name'].casefold(),x['stream'],c.casefold())
            if k not in seen:seen.add(k);rows.append((x['name'],c,x['stream']))
    rows.sort(key=lambda x:(x[1].casefold(),x[0].casefold()));return rows

def write(rows):
    a=['#EXTM3U']
    for n,c,u in rows:
        n=n.replace('"','');c=c.replace('"','');tid=hashlib.sha1(n.encode()).hexdigest()[:12]
        a += [f'#EXTINF:-1 tvg-id="{tid}" tvg-name="{n}" tvg-country="BR" tvg-language="Português" group-title="{c}",{n}',u]
    OUT.write_text('\n'.join(a)+'\n',encoding='utf-8')

async def main():
    global SOURCES_DATA
    SOURCES_DATA=json.loads(SOURCES.read_text(encoding='utf-8'))
    # Diagnóstico novo em cada execução: nunca reaproveitar arquivo antigo.
    write_discovery({},[{'inicio':True,'fontes':SOURCES_DATA}],[],[])
    async with async_playwright() as pw:
        b=await pw.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        p=await b.new_page(user_agent=UA,locale='pt-BR')
        urls=await discover(p);await p.close()
        print(f'Total descoberto: {len(urls)}',flush=True)
        sem=asyncio.Semaphore(6);items=[]
        for start in range(0,len(urls),30):
            res=await asyncio.gather(*(inspect(b,u,sem) for u in urls[start:start+30]));items.extend(res)
            print(f'Inspecionados {min(start+30,len(urls))}/{len(urls)}',flush=True)
        await b.close()
    rows=await validate(items)
    if not rows:
        STATUS.write_text(json.dumps({'erro':'Nenhum canal ativo validado','canais_descobertos':len(urls)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise SystemExit('Nenhum canal ativo validado; lista existente preservada.')
    write(rows)
    STATUS.write_text(json.dumps({'canais_descobertos':len(urls),'canais_com_stream':len(set(r[0] for r in rows)),'entradas_m3u':len(rows),'fontes_estaduais':len(SOURCES_DATA['estados']),'validacao_hls_segmentos':True,'ss_iptv_compatibilidade':True},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Gerado {OUT} com {len(rows)} entradas.',flush=True)

if __name__=='__main__':asyncio.run(main())
