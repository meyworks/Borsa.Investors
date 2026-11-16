"""Offline sanity checks: do not require EGX network access."""
from collector import extract_tables, number, HEADERS
assert len(HEADERS)==22
assert number('١٬٢٣٤٫٥')==1234.5
rows=[['أفراد مصريون','100','90'],['مؤسسات مصرية','10','20'],['أفراد عرب','5','6'],['مؤسسات عربية','9','8'],['أفراد أجانب','7','2'],['مؤسسات أجنبية','9','3']]
assert len(extract_tables([{'headers':['الفئة','شراء','بيع'],'rows':rows}]))==6
try: extract_tables([{'headers':['الفئة','شراء','بيع'],'rows':rows[:-1]}]); raise AssertionError('Incomplete table accepted')
except RuntimeError: pass
print('Offline tests passed')
