from artifact_tool import Workbook,SpreadsheetFile
from collector import HEADERS
from pathlib import Path
import csv
p=Path(__file__).resolve().parent
w=Workbook.create();s=w.worksheets.add('Investor Flows')
s.get_range_by_indexes(0,0,1,len(HEADERS)).values=[HEADERS]
s.get_range_by_indexes(0,0,1,len(HEADERS)).format={'fill':'#153B5B','font':{'bold':True,'color':'#FFFFFF'},'row_height':27}
s.get_range('A:A').format.column_width=18
s.get_range('B:B').format.column_width=18
s.get_range('C:C').format.column_width=55
s.get_range('D:D').format.column_width=28
s.get_range('E:V').format.column_width=23
s.freeze_panes.freeze_rows(1)
m=w.worksheets.add('Read Me')
notes=[['EGX Investor Flows — Stocks Only'],['Source: https://www.egx.com.eg/ar/InvestorsTypeCharts.aspx'],['One row per confirmed market session'],['Buy, Sell, Net for six investor categories'],['Numeric unit to be verified against official EGX page'],['Initial template: no collected market data yet'],['By: Eng. Michael Edward']]
m.get_range('A1:A7').values=notes
m.get_range('A:A').format.column_width=85
SpreadsheetFile.export_xlsx(w).save(str(p/'data'/'investor_flows.xlsx'))
with (p/'data'/'investor_flows.csv').open('w',encoding='utf-8-sig',newline='') as f: csv.writer(f).writerow(HEADERS)
print('created template')
