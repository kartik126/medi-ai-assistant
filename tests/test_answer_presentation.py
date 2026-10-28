"""The main answer and expanded quotation must stay separate in the UI."""
import ast
import pytest
from pathlib import Path


@pytest.mark.parametrize('filename,page_label,link_label', [('test.pdf','physical page','Open original PDF'),('test.docx','converted PDF page','Open cited PDF')])
def test_ui_renders_answer_text_and_quotes_in_separate_locations(filename,page_label,link_label):
    class UI:
        inside=False
        rendered=[]
        links=[]
        labels=[]
        def text(self,value):self.rendered.append((self.inside,value))
        def caption(self,*args):pass
        def link_button(self,*args):self.links.append(args[0])
        def button(self,*args,**kwargs):return False
        def expander(self,*args):self.labels.append(args[0]);return self
        def __enter__(self):self.inside=True
        def __exit__(self,*args):self.inside=False
    tree=ast.parse(Path('frontend/app.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='show_result')
    ui=UI();scope={'st':ui,'BASE':'http://127.0.0.1:8000'}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'frontend/app.py','exec'),scope)
    quote=r'Gene Alteration VAF\nTP53 c.273G>A 17.9%'
    scope['show_result']({'answer':r'TP53 variant allele frequency:\t17.9%. [S1]',
                         'citations':[dict(source_id='S1',filename=filename,page_number=4,quote=quote,chunk_id='id',file_url='/file#page=4',page_text_url='/pages/4')]},'key',[])
    assert ui.rendered==[(False,'TP53 variant allele frequency: 17.9%. [S1]'),(True,'Gene Alteration VAF TP53 c.273G>A 17.9%')]

    assert ui.labels == [f"[S1] {filename} · {page_label} 4"]
    assert ui.links == [link_label]
