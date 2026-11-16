"""EGX daily investor-type collector. Conservative: never write partially parsed values."""
import argparse, csv, json, os, re, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
URL = 'https://www.egx.com.eg/ar/InvestorsTypeCharts.aspx'
GROUPS = ['egyptian_individuals','egyptian_institutions','arab_individuals','arab_institutions','foreign_individuals','foreign_institutions']
HEADERS = ['session_date','scope','source_url','collected_at_cairo'] + [f'{g}_{field}' for g in GROUPS for field in ('buy','sell','net')]
GROUP_TERMS = {
'egyptian_individuals': (['مصري','egypt'], ['افراد','individual','retail']),
'egyptian_institutions': (['مصري','egypt'], ['مؤسسات','institution']),
'arab_individuals': (['عرب','arab'], ['افراد','individual','retail']),
'arab_institutions': (['عرب','arab'], ['مؤسسات','institution']),
'foreign_individuals': (['اجانب','اجنبي','foreign','non arab'], ['افراد','individual','retail']),
'foreign_institutions': (['اجانب','اجنبي','foreign','non arab'], ['مؤسسات','institution']),
}

def norm(s):
    s = str(s).lower().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789'))
    s = re.sub('[\u064b-\u065f\u0670]', '', s)
    for a,b in [('أ','ا'),('إ','ا'),('آ','ا'),('ى','ي')]: s=s.replace(a,b)
    return ' '.join(s.split())

def number(raw):
    s = norm(raw).strip().replace('٬',',').replace('٫','.')
    s = re.sub(r'(?:egp|جنيه|مليون|million|%)', '', s).strip().replace(' ', '')
    if not re.fullmatch(r'-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?',s):
        raise ValueError('Not a plain numerical value: '+repr(raw))
    return float(s.replace(',',''))

def group_match(text):
    t=norm(text)
    possible=[g for g,(nationality,kind) in GROUP_TERMS.items() if any(x in t for x in nationality) and any(x in t for x in kind)]
    return possible[0] if len(possible)==1 else None

def extract_tables(payload):
    """Requires independently labelled buy/sell columns. Do NOT infer chart point roles."""
    matches=[]
    for table in payload:
        hdr=[norm(x) for x in table.get('headers',[])]
        buyidx=next((i for i,h in enumerate(hdr) if 'شراء' in h or h in ('buy','purchases')),None)
        sellidx=next((i for i,h in enumerate(hdr) if 'بيع' in h or h in ('sell','sales')),None)
        if buyidx is None or sellidx is None or buyidx==sellidx: continue
        found={}
        for cells in table.get('rows',[]):
            g=group_match(' '.join(cells[:max(2,min(len(cells),buyidx))]))
            if not g: g=group_match(' '.join(cells))
            if not g or max(buyidx,sellidx)>=len(cells): continue
            try: b,s=number(cells[buyidx]),number(cells[sellidx])
            except ValueError: continue
            if b<0 or s<0: continue
            if g in found and found[g]!=(b,s): raise RuntimeError('Conflicting values for '+g)
            found[g]=(b,s)
        if len(found)==6: matches.append(found)
    if not matches: raise RuntimeError('No fully-labelled table with six groups and buy/sell columns was found; saved diagnostics. No data written.')
    if any(x!=matches[0] for x in matches): raise RuntimeError('Conflicting investor tables on page. No data written.')
    return matches[0]

def maybe_select_stocks(page):
    # Only choose explicit scope; never assume default is stocks.
    labels = [re.compile(r'^\s*أسهم\s*فقط\s*$'), re.compile(r'^\s*الأسهم\s*فقط\s*$'), re.compile(r'^\s*Stocks\s*Only\s*$',re.I)]
    for pattern in labels:
        for selector in [page.get_by_role('option',name=pattern),page.get_by_role('radio',name=pattern),page.get_by_role('button',name=pattern),page.get_by_text(pattern,exact=True)]:
            try:
                if selector.count()==1 and selector.is_visible(timeout=1200):
                    selector.click(timeout=2500)
                    page.wait_for_timeout(1800)
                    return True
            except Exception: pass
    # Native select whose option contains scope label.
    try:
        for select in page.locator('select').all():
            opts=select.locator('option').all()
            for opt in opts:
                if any(p.search(opt.inner_text()) for p in labels):
                    select.select_option(value=opt.get_attribute('value'))
                    page.wait_for_timeout(1800)
                    return True
    except Exception: pass
    return False

def scrape(headless=True):
    ROOT.joinpath('diagnostics').mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=headless)
        page=browser.new_page(locale='ar-EG', timezone_id='Africa/Cairo', viewport={'width':1440,'height':1050})
        try:
            response=page.goto(URL,wait_until='domcontentloaded',timeout=65000)
            if not response or response.status>=400: raise RuntimeError(f'Site HTTP status: {response.status if response else "none"}')
            page.wait_for_timeout(5000)
            selected=maybe_select_stocks(page)
            page.wait_for_timeout(2500)
            page.screenshot(path=str(ROOT/'diagnostics'/'latest.png'),full_page=True)
            (ROOT/'diagnostics'/'latest.html').write_text(page.content(),encoding='utf-8')
            if not selected: raise RuntimeError('Could not confirm selecting "أسهم فقط". Update selector after inspecting diagnostics; no record written.')
            tables=page.evaluate('''() => [...document.querySelectorAll('table')].map(t => ({
              headers:[...t.querySelectorAll('thead tr:last-child th')].map(x=>x.innerText.trim()),
              rows:[...t.querySelectorAll('tbody tr')].map(r=>[...r.querySelectorAll('th,td')].map(x=>x.innerText.trim()))
            }))''')
            (ROOT/'diagnostics'/'tables.json').write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
            values=extract_tables(tables)
            return values
        finally: browser.close()

def append_record(values,date):
    file=ROOT/'data'/'investor_flows.csv'; file.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    if file.exists():
        with file.open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if reader.fieldnames!=HEADERS: raise RuntimeError('CSV schema mismatch; leaving file unchanged')
            rows=list(reader)
    now=datetime.now(ZoneInfo('Africa/Cairo')).isoformat(timespec='seconds')
    new={'session_date':date,'scope':'stocks_only','source_url':URL,'collected_at_cairo':now}
    for g,(b,s) in values.items():
        new[f'{g}_buy']=b;new[f'{g}_sell']=s;new[f'{g}_net']=round(b-s,8)
    if any(r['session_date']==date and r['scope']=='stocks_only' for r in rows):
        print('Existing session, skipping duplicate:',date); return False
    rows.append(new);rows.sort(key=lambda r:r['session_date'])
    temp=file.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=HEADERS);writer.writeheader();writer.writerows(rows)
    temp.replace(file)
    return True

def render_excel():
    """Export daily CSV to a native, editable Excel workbook on each successful run."""
    import xlsxwriter
    path=ROOT/'data'/'investor_flows.xlsx'; csvpath=ROOT/'data'/'investor_flows.csv'
    with csvpath.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    wb=xlsxwriter.Workbook(str(path)); sh=wb.add_worksheet('Investor Flows')
    header=wb.add_format({'bold':1,'font_color':'white','bg_color':'#11395C','border':0})
    datefmt=wb.add_format({'num_format':'yyyy-mm-dd'})
    nfmt=wb.add_format({'num_format':'#,##0.00;[Red](#,##0.00);–'})
    for i,h in enumerate(HEADERS):sh.write(0,i,h,header)
    for row_idx,row in enumerate(rows,1):
        for i,h in enumerate(HEADERS):
            v=row.get(h,'')
            if h=='session_date': sh.write_datetime(row_idx,i,datetime.strptime(v,'%Y-%m-%d'),datefmt)
            elif h.endswith(('_buy','_sell','_net')) and v!='': sh.write_number(row_idx,i,float(v),nfmt)
            else: sh.write_string(row_idx,i,str(v))
    sh.freeze_panes(1,4);sh.autofilter(0,0,len(rows),len(HEADERS)-1)
    sh.set_column(0,0,17);sh.set_column(1,1,16);sh.set_column(2,2,56);sh.set_column(3,3,29)
    sh.set_column(4,len(HEADERS)-1,22)
    meta=wb.add_worksheet('Read Me')
    notes=['EGX Investor Flow Collector','Source: '+URL,'Scope: stocks only (أسهم فقط)', 'Each row = one verified session, without duplicate dates.', 'All numeric values are copied as presented by the source page.','Units: verify on EGX page before interpreting amounts.','No row is created if source, scope or extraction cannot be confirmed.','By: Eng. Michael Edward']
    for i,n in enumerate(notes):meta.write(i,0,n)
    meta.set_column(0,0,95)
    wb.close()

def run():
    arg=argparse.ArgumentParser();arg.add_argument('--date',help='Verified market SESSION date YYYY-MM-DD; defaults to Cairo today')
    arg.add_argument('--headed',action='store_true');arg.add_argument('--diagnostic',action='store_true');a=arg.parse_args()
    now=datetime.now(ZoneInfo('Africa/Cairo'))
    # Do not run on Friday/Saturday or before the market is closed.
    if not a.diagnostic and (now.weekday() in (4,5) or now.hour<17):
        print('Outside eligible market-run window');return
    values=scrape(headless=not a.headed)
    if a.diagnostic:
        print(json.dumps(values,ensure_ascii=False,indent=2));return
    # Session date MUST be independently provided or confirmed by visible page in production.
    # Refuse stamping today's date if the page is stale or if a holiday occurred.
    if not a.date:
        raise RuntimeError('A verified SESSION date is required (--date YYYY-MM-DD); refusing to date stale data by collection time.')
    datetime.strptime(a.date,'%Y-%m-%d')
    if append_record(values,a.date):render_excel(); print('APPENDED:',a.date)
if __name__=='__main__':
    try:run()
    except Exception as e:print('COLLECTION FAILED:',e,file=sys.stderr);sys.exit(1)
